# -*- coding: utf-8 -*-
"""crm-suite Phase 1 · Keel 穿行旅程(2026-10-03 提案版)

落点:Keel 项目空间 tests/journeys.py(本文件可直接 cp 覆盖)。
契约:同目录 crm-invariants.json(结构化不变量,25 条)。

表面约定(与测试机框架实际签名不一致时,只改本文件顶部适配,步骤体不动):
  build_journey(api)         —— Keel journeys 注册入口
  api.as_role(key)           —— envAuth 装配的按角色客户端;键=演示手机号(见 envAuth 片段)
  api.step(段号, 标题, fn)   —— 注册一段;fn 签名 fn(run)
  run.check(名, bool, 证据)  —— 每条断言必须带证据文本;检查名即契约 left 锚点(journey:<段>/<检查名>.passed)
  resp.status / resp.json    —— HTTP 响应(体为 dict)

骨架 9 段:已注册 J0' 冒烟 + J1 录入 + J2 认领 + J3 跟进 + J4 转化 + J5 归属 + J9 越权(7 段);
J6 商机 / J7 订单 / J8 回款 留待 Phase 2(S03/S07/S08)落地后注册。
断言零硬编码 id:全部先建后查、以响应返回值驱动;USCI 按秒生成,旅程可重复执行。
角色事实:演示账号 13800000001~06 / demo123(seed.ts);登录 POST /api/v1/auth/login {phone,password};
token 12h(lib/auth.ts TOKEN_TTL),roleField=user.roleCode。
"""

import re
import time


def build_journey(api):
    st = {}  # 跨段数据总线(lead/customer id、USCI 等),供后续段先建后查

    R02 = api.as_role('13800000001')   # 张主管 R02
    R01a = api.as_role('13800000002')  # 李销售 R01
    R01b = api.as_role('13800000003')  # 王销售 R01
    R01c = api.as_role('13800000004')  # 赵销售 R01
    R05 = api.as_role('13800000006')   # 系统管理员 R05(备用)

    st['usci'] = '91310000' + str(int(time.time()))  # 18 位,按秒唯一

    # ---------- J0' 冒烟 ----------
    def j0(run):
        r = R02.get('/api/v1/customers')
        run.check('J0-主管可读客户列表', r.status == 200, f'GET /api/v1/customers → {r.status}')

    # ---------- J1 录入线索 ----------
    def j1(run):
        r = R01a.post('/api/v1/leads', json={
            'leadType': '自拓线索', 'companyName': 'KEEL穿行公司', 'usci': st['usci'],
            'contactName': '穿行联系人', 'contactPhone': '13858000001',
        })
        run.check('J1-建档201', r.status == 201, f'POST /api/v1/leads → {r.status}')
        lead = r.json['item']
        st['lead_id'] = lead['id']

        d = R01a.get(f"/api/v1/leads/{lead['id']}")
        item = d.json['item']
        li = next(u for u in R01a.get('/api/v1/users').json['items'] if u['phone'] == '13800000002')
        run.check('J1-初态待开发', item['leadStatus'] == '待开发线索', f"leadStatus={item['leadStatus']}")
        run.check('J1-编号XS月流水', bool(re.match(r'^XS\d{6}-\d{4}$', lead['leadNo'])), f"leadNo={lead['leadNo']}")
        run.check('J1-归属本人', item['ownerId'] == li['id'] and item['isPublic'] is False,
                  f"ownerId={item['ownerId']}, li={li['id']}, isPublic={item['isPublic']}")

        # 契约锚点 INV-LEAD-003:同 USCI 全局唯一(换人再建也被拒)
        dup = R01b.post('/api/v1/leads', json={
            'leadType': '自拓线索', 'companyName': '重复USCI公司', 'usci': st['usci'],
        })
        run.check('J1-usci重复409含既有编号',
                  dup.status == 409 and lead['leadNo'] in str(dup.json.get('error', {}).get('message', '')),
                  f"dup → {dup.status}, message={dup.json.get('error', {}).get('message')}")

    # ---------- J2 公海认领(双认领一拒) ----------
    def j2(run):
        r = R01a.post(f"/api/v1/leads/{st['lead_id']}/return")
        run.check('J2-回退单201', r.status == 201, f"return → {r.status}, no={r.json.get('returnNo')}")
        d = R02.post(f"/api/v1/leads/returns/{r.json['id']}/decide", json={'approve': True})
        run.check('J2-回退审批通过', d.json.get('status') == '已通过', f"decide → {d.json.get('status')}")

        pool = R01b.get('/api/v1/leads/pool')
        run.check('J2-已入公海', any(i['id'] == st['lead_id'] for i in pool.json['items']),
                  f"pool total={pool.json['total']}")

        c1 = R01b.post(f"/api/v1/leads/{st['lead_id']}/claim")
        c2 = R01c.post(f"/api/v1/leads/{st['lead_id']}/claim")
        run.check('J2-认领互斥一成一拒',
                  c1.status == 200 and bool(re.match(r'^RL\d{6}-\d{4}$', c1.json['claimNo']))
                  and c2.status == 409 and c2.json['error']['code'] == 'CLAIM_RACE_LOST',
                  f"claim#1 → {c1.status} no={c1.json.get('claimNo')}; claim#2 → {c2.status} "
                  f"code={c2.json.get('error', {}).get('code')}")

        pool2 = R01b.get('/api/v1/leads/pool')
        run.check('J2-移出公海', all(i['id'] != st['lead_id'] for i in pool2.json['items']),
                  f"pool total={pool2.json['total']}")

    # ---------- J3 跟进(联系人挂载) ----------
    def j3(run):
        c = R01b.post('/api/v1/contacts', json={
            'contactType': '线索', 'name': '穿行联系人甲', 'phone': '13858000002', 'leadId': st['lead_id'],
        })
        run.check('J3-挂载建档201', c.status == 201, f'POST /api/v1/contacts → {c.status}')
        st['contact_id'] = c.json['item']['id']

        lst = R01b.get(f"/api/v1/contacts?leadId={st['lead_id']}")
        masked = lst.json['items'][0]['phone']
        run.check('J3-列表脱敏138****0002', lst.json['total'] == 1 and masked == '138****0002',
                  f"total={lst.json['total']}, phone={masked}")

        dup = R01b.post('/api/v1/contacts', json={
            'contactType': '线索', 'name': '穿行联系人甲', 'phone': '13958000002', 'leadId': st['lead_id'],
        })
        run.check('J3-同对象同名409', dup.status == 409, f'dup → {dup.status}')

    # ---------- J4 转化(单向)+ 状态机关键边 ----------
    def j4(run):
        s = R01b.post(f"/api/v1/leads/{st['lead_id']}/status", json={'toStatus': '商机线索'})
        run.check('J4-商机线索200', s.status == 200, f'status → {s.json}')

        # lead2:待开发线索禁转化 + 无效激活权限边(契约 INV-CONV-009 / INV-LEAD-002)
        l2 = R01a.post('/api/v1/leads', json={'leadType': '自拓线索', 'companyName': 'KEEL状态机公司'})
        st['lead2_id'] = l2.json['item']['id']
        pre = R01a.post('/api/v1/customers', json={'leadId': st['lead2_id']})
        run.check('J4-待开发线索禁转化400', pre.status == 400, f'convert(待开发) → {pre.status}')

        inv2 = R01a.post(f"/api/v1/leads/{st['lead2_id']}/status",
                         json={'toStatus': '无效线索', 'reason': '穿行验证激活权限用'})
        run.check('J4-转无效原因合规200', inv2.status == 200, f'→ {inv2.status}')
        act1 = R01a.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'})
        act2 = R02.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'})
        run.check('J4-无效激活仅主管(403/200)',
                  act1.status == 403 and act2.status == 200,
                  f'R01 → {act1.status}, R02 → {act2.status}')
        back = R01a.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'})
        run.check('J4-同状态迁移400', back.status == 400, f'→ {back.status}')

        # 主链转化(lead1,现归王)
        v = R01b.post('/api/v1/customers', json={'leadId': st['lead_id']})
        run.check('J4-转化201', v.status == 201, f"POST /api/v1/customers → {v.status}, no={v.json['item'].get('customerNo')}")
        cust = v.json['item']
        st['customer_id'] = cust['id']

        cd = R01b.get(f"/api/v1/customers/{cust['id']}")
        run.check('J4-带出与初态及联系人落客户',
                  cust['companyName'] == 'KEEL穿行公司' and cust['customerStatus'] == '未成交'
                  and len(cd.json['contacts']) >= 1,
                  f"companyName={cust['companyName']}, status={cust['customerStatus']}, "
                  f"contacts={len(cd.json['contacts'])}")

        again = R01b.post('/api/v1/customers', json={'leadId': st['lead_id']})
        run.check('J4-禁再转化409(LEAD_ALREADY_CONVERTED)',
                  again.status == 409 and again.json['error']['code'] == 'LEAD_ALREADY_CONVERTED',
                  f'again → {again.status}, code={again.json.get("error", {}).get("code")}')

        d = R01b.get(f"/api/v1/leads/{st['lead_id']}")
        run.check('J4-线索回写客户', d.json['item'].get('customerId') == cust['id'],
                  f"customerId={d.json['item'].get('customerId')} vs {cust['id']}")

        blocked = R01b.post(f"/api/v1/leads/{st['lead_id']}/status",
                            json={'toStatus': '无效线索', 'reason': '穿行验证下游保护用'})
        run.check('J4-下游保护400', blocked.status == 400, f'置无效 → {blocked.status}')
        rev = R01b.post(f"/api/v1/leads/{st['lead_id']}/status", json={'toStatus': '待开发线索'})
        run.check('J4-商机不可回退待开发400', rev.status == 400, f'→ {rev.status}')

    # ---------- J5 归属流转(变更留痕) ----------
    def j5(run):
        users = R02.get('/api/v1/users').json['items']
        st['zhao_id'] = next(u['id'] for u in users if u['phone'] == '13800000004')

        t = R01b.post(f"/api/v1/customers/{st['customer_id']}/transfer",
                      json={'toOwnerId': st['zhao_id'], 'reason': 'KEEL穿行转交'})
        run.check('J5-转交单201', t.status == 201 and bool(re.match(r'^ZJ\d{6}-\d{4}$', t.json['transferNo'])),
                  f"transfer → {t.status}, no={t.json.get('transferNo')}")
        d1 = R02.post(f"/api/v1/customers/transfers/{t.json['id']}/decide", json={'approve': True})
        run.check('J5-转交审批通过', d1.json.get('status') == '已通过', f"decide → {d1.json.get('status')}")

        rr = R01c.post(f"/api/v1/customers/{st['customer_id']}/return")
        run.check('J5-回退单201', rr.status == 201, f"return → {rr.status}, no={rr.json.get('returnNo')}")
        d2 = R02.post(f"/api/v1/customers/returns/{rr.json['id']}/decide", json={'approve': True})
        run.check('J5-回退审批通过', d2.json.get('status') == '已通过', f"decide → {d2.json.get('status')}")

        cl = R01b.post(f"/api/v1/customers/{st['customer_id']}/claim")
        run.check('J5-认领回抢200', cl.status == 200, f'claim → {cl.status}, no={cl.json.get("claimNo")}')

        detail = R02.get(f"/api/v1/customers/{st['customer_id']}")
        logs = detail.json['ownerLogs']
        wang_id = next(u['id'] for u in users if u['phone'] == '13800000003')
        run.check('J5-认领后归属回王', detail.json['item']['ownerId'] == wang_id,
                  f"ownerId={detail.json['item']['ownerId']}, wang={wang_id}")
        run.check('J5-留痕四动作齐全',
                  [g['action'] for g in logs] == ['create', 'transfer', 'return', 'claim'],
                  f"actions={[g['action'] for g in logs]}")
        run.check('J5-留痕单据号可互查',
                  str(logs[1]['ref_no']).startswith('ZJ') and str(logs[2]['ref_no']).startswith('TH')
                  and str(logs[3]['ref_no']).startswith('RL'),
                  f"refs={[g['ref_no'] for g in logs]}")
        st['final_owner_id'] = detail.json['item']['ownerId']

    # ---------- J9 越权回归(97ac7e5) ----------
    def j9(run):
        # 李全程未持有该客户(现归王)→ 详情 403
        x = R01a.get(f"/api/v1/customers/{st['customer_id']}")
        run.check('J9-越权读客户403(97ac7e5回归)', x.status == 403,
                  f"R01a GET /api/v1/customers/{st['customer_id']} → {x.status}")
        m = R02.get(f"/api/v1/customers/{st['customer_id']}")
        run.check('J9-主管可读200', m.status == 200, f'R02 → {m.status}')

        # 线索归王:李读其联系人 → 403
        cx = R01a.get(f"/api/v1/contacts/{st['contact_id']}")
        run.check('J9-越权读联系人403', cx.status == 403,
                  f"R01a GET /api/v1/contacts/{st['contact_id']} → {cx.status}")

        # 列表行级隔离:李的客户列表不含王的客户
        lst = R01a.get('/api/v1/customers')
        run.check('J9-列表行级隔离',
                  all(i['id'] != st['customer_id'] for i in lst.json['items']),
                  f"total={lst.json['total']}, excluded={st['customer_id']}")

    api.step("J0'", '冒烟', j0)
    api.step('J1', '录入线索', j1)
    api.step('J2', '公海认领(互斥)', j2)
    api.step('J3', '跟进·联系人挂载', j3)
    api.step('J4', '转化(单向)+状态机边', j4)
    api.step('J5', '归属流转(留痕)', j5)
    api.step('J9', '越权回归', j9)
    # api.step('J6', '商机阶段推进', ...)   # Phase 2:S03 落地后注册
    # api.step('J7', '订单三源汇聚', ...)   # Phase 2:S07 落地后注册
    # api.step('J8', '回款核销', ...)       # Phase 2:S08 落地后注册
