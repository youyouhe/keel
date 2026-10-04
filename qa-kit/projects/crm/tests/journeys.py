# -*- coding: utf-8 -*-
"""crm-suite Phase 1 · Keel 穿行旅程(2026-10-03 提案版)

落点:Keel 项目空间 tests/journeys.py(本文件可直接 cp 覆盖)。
契约:同目录 crm-invariants.json(结构化不变量,25 条)。

表面约定(与测试机框架实际签名不一致时,只改本文件顶部适配,步骤体不动):
  build_journey(api)         —— Keel journeys 注册入口
  api.as_role(key)           —— envAuth 装配的按角色客户端;键=演示手机号(见 envAuth 片段)
  api.step(段号, 标题, fn)   —— 注册一段;fn 签名 fn(run)
  run.check(名, bool, 证据)  —— 每条断言必须带证据文本;检查名即契约 left 锚点(journey:<段>/<检查名>.passed)

骨架 9+1 段:已注册 J0' 冒烟 + J1 录入 + J2 认领 + J3 跟进 + J4 转化 + J5 归属 + J6 商机 + J7 订单 + J8 回款 + J9 越权(10 段)。
断言零硬编码 id:全部先建后查、以响应返回值驱动;USCI 按秒生成,旅程可重复执行。
角色事实:演示账号 13800000001~07 / demo123(seed.ts);登录 POST /api/v1/auth/login {phone,password};
token 12h(lib/auth.ts TOKEN_TTL),roleField=user.roleCode。

适配记录:
  2026-10-04 适配一(j_3677cd4e 首轮反馈):4xx 抛 ApiError → 顶部加 try_call 容错(异常式归一化)。
  2026-10-04 适配二(v0.10 客户端,report-20261004-005039):客户端改双语义——201→200 已修
    (6 处 201 断言保持严格,应全绿);4xx 不再抛异常,改返回 ApiResult 对象。
    因此 try_call 升级为**双语义归一化**:不假设客户端抛不抛,所有调用(含 2xx 直通)一律过
    _norm() 拍平成 {'status': int, 'json': dict},断言统一 d['status']/d['json'] 访问,
    彻底消除对客户端响应类型的依赖;旧异常语义(ApiError)在 except 分支兼容保留。
  2026-10-04 P2 收尾:注册 J6/J7/J8 三段(S03 商机/S07 订单/S08 回款,server fbe4f36 已交付)。
    回款日期恒用 '2026-10-03'(≤UTC 今天,不受运行日影响);铺底复用 st 总线先建后查。
"""

import json
import re
import time


def _norm(r):
    """把客户端响应对象拍平为 {'status': int, 'json': dict},不假设其具体类型。

    status:优先 .status,回退 .status_code(不同客户端命名不一)。
    json:  .json 可能是属性或方法(callable 则调用);取不到或非 dict 时包成
           {'raw': str(...)},保证下游 .get()/['error'] 访问不炸。
    """
    st = getattr(r, 'status', None) or getattr(r, 'status_code', None)
    js = getattr(r, 'json', None)
    if callable(js):
        try:
            js = js()
        except Exception:  # 客户端 json() 失败时留空体,断言按缺失处理
            js = {}
    if isinstance(js, str):  # 客户端 .json 可能返回原始响应文本,尽力解析为 dict
        try:
            js = json.loads(js)
        except Exception:
            js = {'raw': js}
    if isinstance(js, dict) and 'error' not in js and 'code' in js and 'message' in js:
        # Keel 客户端把 CRM 错误体 {error:{code,message}} 拍平成顶层 {code,message},此处还原外形
        js = {'error': js}
    if not isinstance(js, dict):
        js = {'raw': str(js)}
    return {'status': st, 'json': js}


def try_call(fn):
    """双语义归一化:所有请求(含预期 2xx 的直通路径)都经此拍平。

    新语义(v0.10):客户端对 4xx 返回 ApiResult 对象 → 正常返回,走 _norm。
    旧语义(兼容保留):客户端对 4xx 抛 ApiError → except 分支按
    str(e) 行首 `^(\\d{3})\\s+(\\w+)` 提取状态码与机器码;完全无形状时 status=0
    (不等于任何预期码,断言红而不中止穿行)。
    """
    try:
        return _norm(fn())
    except Exception as e:  # 旧客户端语义:4xx 抛 ApiError,归一化兜底
        m = str(e)
        mm = re.match(r'^(\d{3})\s+(\w+)', m)
        return {'status': int(mm.group(1)) if mm else 0,
                'json': {'error': {'code': mm.group(2) if mm else '', 'message': m}}}


def build_journey(api):
    st = {}  # 跨段数据总线(lead/customer id、USCI 等),供后续段先建后查

    R02 = api.as_role('13800000001')   # 张主管 R02
    R01a = api.as_role('13800000002')  # 李销售 R01
    R01b = api.as_role('13800000003')  # 王销售 R01
    R01c = api.as_role('13800000004')  # 赵销售 R01
    R04 = api.as_role('13800000005')   # 钱财务 R04(J8 回款)
    R05 = api.as_role('13800000006')   # 系统管理员 R05(备用)

    st['usci'] = '91310000' + str(int(time.time()))  # 18 位,按秒唯一

    # ---------- J0' 冒烟 ----------
    def j0(run):
        r = try_call(lambda: R02.get('/api/v1/customers'))
        run.check('J0-主管可读客户列表', r['status'] == 200, f"GET /api/v1/customers → {r['status']}")

    # ---------- J1 录入线索 ----------
    def j1(run):
        r = try_call(lambda: R01a.post('/api/v1/leads', json={
            'leadType': '自拓线索', 'companyName': 'KEEL穿行公司', 'usci': st['usci'],
            'contactName': '穿行联系人', 'contactPhone': '13858000001',
        }))
        run.check('J1-建档201', r['status'] == 201,
                  f"POST /api/v1/leads → {r['status']};服务端 curl/vitest 均为 201"
                  '(v0.10 客户端已修 201→200,此处保持严格 201)')
        lead = r['json']['item']
        st['lead_id'] = lead['id']

        d = try_call(lambda: R01a.get(f"/api/v1/leads/{lead['id']}"))
        item = d['json']['item']
        li = next(u for u in try_call(lambda: R01a.get('/api/v1/users'))['json']['items']
                  if u['phone'] == '13800000002')
        run.check('J1-初态待开发', item['leadStatus'] == '待开发线索', f"leadStatus={item['leadStatus']}")
        run.check('J1-编号XS月流水', bool(re.match(r'^XS\d{6}-\d{4}$', lead['leadNo'])), f"leadNo={lead['leadNo']}")
        run.check('J1-归属本人', item['ownerId'] == li['id'] and item['isPublic'] is False,
                  f"ownerId={item['ownerId']}, li={li['id']}, isPublic={item['isPublic']}")

        # 契约锚点 INV-LEAD-003:同 USCI 全局唯一(换人再建也被拒;4xx 由 try_call 归一化)
        dup = try_call(lambda: R01b.post('/api/v1/leads', json={
            'leadType': '自拓线索', 'companyName': '重复USCI公司', 'usci': st['usci'],
        }))
        run.check('J1-usci重复409含既有编号',
                  dup['status'] == 409 and lead['leadNo'] in str(dup['json'].get('error', {}).get('message', '')),
                  f"dup → {dup['status']}, message={dup['json'].get('error', {}).get('message')}")

    # ---------- J2 公海认领(双认领一拒) ----------
    def j2(run):
        r = try_call(lambda: R01a.post(f"/api/v1/leads/{st['lead_id']}/return"))
        run.check('J2-回退单201', r['status'] == 201,
                  f"return → {r['status']}, no={r['json'].get('returnNo')};保持严格 201(v0.10 已修)")
        d = try_call(lambda: R02.post(f"/api/v1/leads/returns/{r['json']['id']}/decide", json={'approve': True}))
        run.check('J2-回退审批通过', d['json'].get('status') == '已通过', f"decide → {d['json'].get('status')}")

        pool = try_call(lambda: R01b.get('/api/v1/leads/pool'))
        run.check('J2-已入公海', any(i['id'] == st['lead_id'] for i in pool['json']['items']),
                  f"pool total={pool['json']['total']}")

        c1 = try_call(lambda: R01b.post(f"/api/v1/leads/{st['lead_id']}/claim"))
        c2 = try_call(lambda: R01c.post(f"/api/v1/leads/{st['lead_id']}/claim"))
        run.check('J2-认领互斥一成一拒',
                  c1['status'] == 200 and bool(re.match(r'^RL\d{6}-\d{4}$', c1['json']['claimNo']))
                  and c2['status'] == 409 and c2['json']['error']['code'] == 'CLAIM_RACE_LOST',
                  f"claim#1 → {c1['status']} no={c1['json'].get('claimNo')}; claim#2 → {c2['status']} "
                  f"code={c2['json'].get('error', {}).get('code')}")

        pool2 = try_call(lambda: R01b.get('/api/v1/leads/pool'))
        run.check('J2-移出公海', all(i['id'] != st['lead_id'] for i in pool2['json']['items']),
                  f"pool total={pool2['json']['total']}")

    # ---------- J3 跟进(联系人挂载) ----------
    def j3(run):
        c = try_call(lambda: R01b.post('/api/v1/contacts', json={
            'contactType': '线索', 'name': '穿行联系人甲', 'phone': '13858000002', 'leadId': st['lead_id'],
        }))
        run.check('J3-挂载建档201', c['status'] == 201,
                  f"POST /api/v1/contacts → {c['status']};保持严格 201(v0.10 已修)")
        st['contact_id'] = c['json']['item']['id']

        lst = try_call(lambda: R01b.get(f"/api/v1/contacts?leadId={st['lead_id']}"))
        masked = lst['json']['items'][0]['phone']
        run.check('J3-列表脱敏138****0002', lst['json']['total'] == 1 and masked == '138****0002',
                  f"total={lst['json']['total']}, phone={masked}")

        dup = try_call(lambda: R01b.post('/api/v1/contacts', json={
            'contactType': '线索', 'name': '穿行联系人甲', 'phone': '13958000002', 'leadId': st['lead_id'],
        }))
        run.check('J3-同对象同名409', dup['status'] == 409, f"dup → {dup['status']}")

    # ---------- J4 转化(单向)+ 状态机关键边 ----------
    def j4(run):
        s = try_call(lambda: R01b.post(f"/api/v1/leads/{st['lead_id']}/status", json={'toStatus': '商机线索'}))
        run.check('J4-商机线索200', s['status'] == 200, f"status → {s['json']}")

        # lead2:待开发线索禁转化 + 无效激活权限边(契约 INV-CONV-009 / INV-LEAD-002)
        l2 = try_call(lambda: R01a.post('/api/v1/leads', json={'leadType': '自拓线索', 'companyName': 'KEEL状态机公司'}))
        st['lead2_id'] = l2['json']['item']['id']
        pre = try_call(lambda: R01a.post('/api/v1/customers', json={'leadId': st['lead2_id']}))
        run.check('J4-待开发线索禁转化400', pre['status'] == 400, f'convert(待开发) → {pre["status"]}')

        inv2 = try_call(lambda: R01a.post(f"/api/v1/leads/{st['lead2_id']}/status",
                                          json={'toStatus': '无效线索', 'reason': '穿行验证激活权限用'}))
        run.check('J4-转无效原因合规200', inv2['status'] == 200, f"→ {inv2['status']}")
        act1 = try_call(lambda: R01a.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'}))
        act2 = try_call(lambda: R02.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'}))
        run.check('J4-无效激活仅主管(403/200)',
                  act1['status'] == 403 and act2['status'] == 200,
                  f'R01 → {act1["status"]}, R02 → {act2["status"]}')
        back = try_call(lambda: R01a.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'}))
        run.check('J4-同状态迁移400', back['status'] == 400, f'→ {back["status"]}')

        # 主链转化(lead1,现归王)
        v = try_call(lambda: R01b.post('/api/v1/customers', json={'leadId': st['lead_id']}))
        run.check('J4-转化201', v['status'] == 201,
                  f"POST /api/v1/customers → {v['status']}, no={v['json']['item'].get('customerNo')};"
                  '保持严格 201(v0.10 已修)')
        cust = v['json']['item']
        st['customer_id'] = cust['id']

        cd = try_call(lambda: R01b.get(f"/api/v1/customers/{cust['id']}"))
        run.check('J4-带出与初态及联系人落客户',
                  cust['companyName'] == 'KEEL穿行公司' and cust['customerStatus'] == '未成交'
                  and len(cd['json']['contacts']) >= 1,
                  f"companyName={cust['companyName']}, status={cust['customerStatus']}, "
                  f"contacts={len(cd['json']['contacts'])}")

        again = try_call(lambda: R01b.post('/api/v1/customers', json={'leadId': st['lead_id']}))
        run.check('J4-禁再转化409(LEAD_ALREADY_CONVERTED)',
                  again['status'] == 409 and again['json']['error']['code'] == 'LEAD_ALREADY_CONVERTED',
                  f'again → {again["status"]}, code={again["json"].get("error", {}).get("code")}')

        d = try_call(lambda: R01b.get(f"/api/v1/leads/{st['lead_id']}"))
        run.check('J4-线索回写客户', d['json']['item'].get('customerId') == cust['id'],
                  f"customerId={d['json']['item'].get('customerId')} vs {cust['id']}")

        # 转化守卫(服务端 2026-10-04 起):已转化线索任何迁移(同状态重复除外)→ 409 LEAD_CONVERTED_LOCKED,
        # 先于边/原因/下游检查;PUT 编辑锁定同码,该断面由 vitest CRM-J4-015 承载
        blocked = try_call(lambda: R01b.post(f"/api/v1/leads/{st['lead_id']}/status",
                                             json={'toStatus': '无效线索', 'reason': '穿行验证下游保护用'}))
        run.check('J4-下游保护409(已转化锁定)',
                  blocked['status'] == 409 and blocked['json']['error']['code'] == 'LEAD_CONVERTED_LOCKED',
                  f'置无效 → {blocked["status"]}, code={blocked["json"].get("error", {}).get("code")}')
        lock = try_call(lambda: R01b.post(f"/api/v1/leads/{st['lead_id']}/status", json={'toStatus': '待开发线索'}))
        run.check('J4-转化后锁定(状态迁移409)',
                  lock['status'] == 409 and lock['json']['error']['code'] == 'LEAD_CONVERTED_LOCKED',
                  f'商机→待开发 → {lock["status"]}, code={lock["json"].get("error", {}).get("code")}')

        # 未转化线索的非法边语义保持 400:lead2(归李)升商机后回退待开发
        p2 = try_call(lambda: R01a.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '商机线索'}))
        run.check('J4-lead2升商机200', p2['status'] == 200, f'→ {p2["status"]}')
        rev = try_call(lambda: R01a.post(f"/api/v1/leads/{st['lead2_id']}/status", json={'toStatus': '待开发线索'}))
        run.check('J4-商机不可回退待开发400', rev['status'] == 400, f'→ {rev["status"]}')

    # ---------- J5 归属流转(变更留痕) ----------
    def j5(run):
        users = try_call(lambda: R02.get('/api/v1/users'))['json']['items']
        st['zhao_id'] = next(u['id'] for u in users if u['phone'] == '13800000004')
        wang_id = next(u['id'] for u in users if u['phone'] == '13800000003')

        t = try_call(lambda: R01b.post(f"/api/v1/customers/{st['customer_id']}/transfer",
                                       json={'toOwnerId': st['zhao_id'], 'reason': 'KEEL穿行转交'}))
        run.check('J5-转交单201',
                  t['status'] == 201 and bool(re.match(r'^ZJ\d{6}-\d{4}$', t['json']['transferNo'])),
                  f"transfer → {t['status']}, no={t['json'].get('transferNo')};保持严格 201(v0.10 已修)")
        d1 = try_call(lambda: R02.post(f"/api/v1/customers/transfers/{t['json']['id']}/decide",
                                       json={'approve': True}))
        run.check('J5-转交审批通过', d1['json'].get('status') == '已通过', f"decide → {d1['json'].get('status')}")

        rr = try_call(lambda: R01c.post(f"/api/v1/customers/{st['customer_id']}/return"))
        run.check('J5-回退单201', rr['status'] == 201,
                  f"return → {rr['status']}, no={rr['json'].get('returnNo')};保持严格 201(v0.10 已修)")
        d2 = try_call(lambda: R02.post(f"/api/v1/customers/returns/{rr['json']['id']}/decide",
                                       json={'approve': True}))
        run.check('J5-回退审批通过', d2['json'].get('status') == '已通过', f"decide → {d2['json'].get('status')}")

        cl = try_call(lambda: R01b.post(f"/api/v1/customers/{st['customer_id']}/claim"))
        run.check('J5-认领回抢200', cl['status'] == 200,
                  f"claim → {cl['status']}, no={cl['json'].get('claimNo')}")

        detail = try_call(lambda: R02.get(f"/api/v1/customers/{st['customer_id']}"))
        logs = detail['json']['ownerLogs']
        run.check('J5-认领后归属回王', detail['json']['item']['ownerId'] == wang_id,
                  f"ownerId={detail['json']['item']['ownerId']}, wang={wang_id}")
        run.check('J5-留痕四动作齐全',
                  [g['action'] for g in logs] == ['create', 'transfer', 'return', 'claim'],
                  f"actions={[g['action'] for g in logs]}")
        run.check('J5-留痕单据号可互查',
                  str(logs[1]['ref_no']).startswith('ZJ') and str(logs[2]['ref_no']).startswith('TH')
                  and str(logs[3]['ref_no']).startswith('RL'),
                  f"refs={[g['ref_no'] for g in logs]}")

    # ---------- J9 越权回归(97ac7e5) ----------
    def j9(run):
        # 李全程未持有该客户(现归王)→ 详情 403(4xx 由 try_call 归一化,不中止)
        x = try_call(lambda: R01a.get(f"/api/v1/customers/{st['customer_id']}"))
        run.check('J9-越权读客户403(97ac7e5回归)', x['status'] == 403,
                  f"R01a GET /api/v1/customers/{st['customer_id']} → {x['status']}")
        m = try_call(lambda: R02.get(f"/api/v1/customers/{st['customer_id']}"))
        run.check('J9-主管可读200', m['status'] == 200, f"R02 → {m['status']}")

        # 线索归王:李读其联系人 → 403
        cx = try_call(lambda: R01a.get(f"/api/v1/contacts/{st['contact_id']}"))
        run.check('J9-越权读联系人403', cx['status'] == 403,
                  f"R01a GET /api/v1/contacts/{st['contact_id']} → {cx['status']}")

        # 列表行级隔离:李的客户列表不含王的客户
        lst = try_call(lambda: R01a.get('/api/v1/customers'))
        run.check('J9-列表行级隔离',
                  all(i['id'] != st['customer_id'] for i in lst['json']['items']),
                  f"total={lst['json']['total']}, excluded={st['customer_id']}")

    # ---------- J6 商机阶段推进(S03) ----------
    def j6(run):
        # 铺底:李建线索 → 商机线索 → 转化客户(转化链已在 J1~J4 断言,此处仅校验关键态)
        lead = try_call(lambda: R01a.post('/api/v1/leads', json={
            'leadType': '自拓线索', 'companyName': 'KEEL商机公司',
            'contactName': '商机联系人', 'contactPhone': '13858000003',
        }))
        run.check('J6-铺底线索201', lead['status'] == 201, f"POST /api/v1/leads → {lead['status']}")
        st['j6_lead_id'] = lead['json']['item']['id']
        try_call(lambda: R01a.post(f"/api/v1/leads/{st['j6_lead_id']}/status", json={'toStatus': '商机线索'}))
        cust = try_call(lambda: R01a.post('/api/v1/customers', json={'leadId': st['j6_lead_id']}))
        st['j6_customer_id'] = cust['json']['item']['id']

        # 建档:初始阶段恒「验证客户」10%,SY 编号
        opp = try_call(lambda: R01a.post('/api/v1/opportunities', json={
            'opportunityName': 'KEEL主商机', 'opportunityType': '新购', 'customerId': st['j6_customer_id'],
        }))
        item = opp['json']['item']
        st['j6_win_opp_id'] = item['id']
        run.check('J6-建档初始阶段',
                  opp['status'] == 201 and bool(re.match(r'^SY\d{6}-\d{4}$', item['opportunityNo']))
                  and item['stage'] == '验证客户' and item['stagePercent'] == 10,
                  f"POST /api/v1/opportunities → {opp['status']}, no={item['opportunityNo']}, "
                  f"stage={item['stage']}({item['stagePercent']}%)")

        # 阶段推进:验证客户→需求确定→方案报价→谈判审核,概率随阶段派生(50%/80% 前置为 P2 降级 hook)
        ok = True
        seq = []
        for stage, pct in [('需求确定', 30), ('方案报价', 50), ('谈判审核', 80)]:
            r = try_call(lambda s=stage: R01a.post(f"/api/v1/opportunities/{st['j6_win_opp_id']}/stage",
                                                   json={'toStage': s}))
            ok = ok and r['status'] == 200 and r['json']['stagePercent'] == pct
            seq.append(f"{stage}:{r['status']}")
        run.check('J6-阶段推进概率派生', ok, f"推进 {'; '.join(seq)}")

        # WIN 结单:金额必填;结单后赢单 100%
        bad = try_call(lambda: R01a.post(f"/api/v1/opportunities/{st['j6_win_opp_id']}/close", json={'result': 'WIN'}))
        run.check('J6-赢单金额必填400', bad['status'] == 400, f"无金额结单 → {bad['status']}")
        win = try_call(lambda: R01a.post(f"/api/v1/opportunities/{st['j6_win_opp_id']}/close",
                                         json={'result': 'WIN', 'finalAmount': 100000}))
        run.check('J6-WIN结单赢单100',
                  win['status'] == 200 and win['json']['stage'] == '赢单' and win['json']['stagePercent'] == 100,
                  f"close → {win['status']}, {win['json'].get('stage')}({win['json'].get('stagePercent')}%)")

        # 客户联动:赢单同事务把客户未成交 → 已成交
        d = try_call(lambda: R01a.get(f"/api/v1/customers/{st['j6_customer_id']}"))
        run.check('J6-客户联动已成交', d['json']['item']['customerStatus'] == '已成交',
                  f"customerStatus={d['json']['item']['customerStatus']}")

        # 终态只读:编辑 409
        lock = try_call(lambda: R01a.put(f"/api/v1/opportunities/{st['j6_win_opp_id']}", json={'opportunityName': 'X'}))
        run.check('J6-终态只读409', lock['status'] == 409, f"PUT 终态商机 → {lock['status']}")

        # 第二商机输单:原因≥5 字,客户状态不回退(仍已成交)
        opp2 = try_call(lambda: R01a.post('/api/v1/opportunities', json={
            'opportunityName': 'KEEL辅商机', 'opportunityType': '续费', 'customerId': st['j6_customer_id'],
        }))
        st['j6_lose_opp_id'] = opp2['json']['item']['id']
        lose = try_call(lambda: R01a.post(f"/api/v1/opportunities/{st['j6_lose_opp_id']}/close",
                                          json={'result': 'LOSE', 'loseReason': '穿行验证输单原因'}))
        d2 = try_call(lambda: R01a.get(f"/api/v1/customers/{st['j6_customer_id']}"))
        run.check('J6-输单不改客户状态',
                  lose['status'] == 200 and lose['json']['stage'] == '丢失客户'
                  and d2['json']['item']['customerStatus'] == '已成交',
                  f"输单 → {lose['status']} {lose['json'].get('stage')}; "
                  f"客户仍 {d2['json'].get('item', {}).get('customerStatus')}")

    # ---------- J7 订单三源汇聚(S07) ----------
    def j7(run):
        # 非赢单商机拒(输单商机建单 → 400)
        bad = try_call(lambda: R02.post('/api/v1/orders', json={
            'opportunityId': st['j6_lose_opp_id'], 'signDate': '2026-10-01',
            'purchaseType': '销售', 'paymentMethod': '转账', 'totalAmount': 100000,
        }))
        run.check('J7-非赢单拒400', bad['status'] == 400,
                  f"输单商机建单 → {bad['status']}, {bad['json'].get('error', {}).get('message')}")

        # 赢单商机建单:DD 编号/待确认;quote/contract 为 P2 降级口径(不传)
        o = try_call(lambda: R02.post('/api/v1/orders', json={
            'opportunityId': st['j6_win_opp_id'], 'signDate': '2026-10-01',
            'purchaseType': '销售', 'paymentMethod': '转账', 'totalAmount': 100000,
        }))
        item = o['json']['item']
        st['j7_order_id'] = item['id']
        run.check('J7-建单201待确认',
                  o['status'] == 201 and bool(re.match(r'^DD\d{6}-\d{4}$', item['orderNo']))
                  and item['status'] == '待确认',
                  f"POST /api/v1/orders → {o['status']}, no={item['orderNo']}, status={item['status']}")
        d = try_call(lambda: R02.get(f"/api/v1/orders/{st['j7_order_id']}"))
        run.check('J7-类别默认取商机类型', d['json']['item']['orderCategory'] == '新购',
                  f"orderCategory={d['json']['item']['orderCategory']}(商机类型=新购)")

        # 未回款不可完成;生效开放回款
        early = try_call(lambda: R02.post(f"/api/v1/orders/{st['j7_order_id']}/status", json={'toStatus': '已完成'}))
        run.check('J7-未回款完成400', early['status'] == 400, f"未回款直接完成 → {early['status']}")
        eff = try_call(lambda: R02.post(f"/api/v1/orders/{st['j7_order_id']}/status", json={'toStatus': '已生效'}))
        run.check('J7-生效200', eff['json'].get('status') == '已生效', f"生效 → {eff['json'].get('status')}")

    # ---------- J8 回款核销(S08;回款日期恒 ≤2026-10-03,UTC 今天口径) ----------
    def j8(run):
        # 计划两期(HK):60% + 40%
        p1 = try_call(lambda: R04.post('/api/v1/receipts/plans', json={
            'orderId': st['j7_order_id'], 'expectedAmount': 60000, 'expectedDate': '2026-10-20'}))
        p2 = try_call(lambda: R04.post('/api/v1/receipts/plans', json={
            'orderId': st['j7_order_id'], 'expectedAmount': 40000, 'expectedDate': '2026-11-20'}))
        run.check('J8-计划两期201',
                  p1['status'] == 201 and p2['status'] == 201
                  and bool(re.match(r'^HK\d{6}-\d{4}$', p1['json']['item']['planNo'])),
                  f"plans → {p1['status']}/{p2['status']}, no={p1['json']['item']['planNo']}")

        # 超额未确认 → 409 RECEIPT_OVER_AMOUNT
        over = try_call(lambda: R04.post('/api/v1/receipts', json={
            'orderId': st['j7_order_id'], 'receiptDate': '2026-10-03', 'receiptAmount': 120000}))
        run.check('J8-超额确认409',
                  over['status'] == 409 and over['json']['error']['code'] == 'RECEIPT_OVER_AMOUNT',
                  f"120000 > 未收 100000 → {over['status']}, code={over['json'].get('error', {}).get('code')}")

        # 收 60000:自动核销第一期收齐(SK 编号)
        r1 = try_call(lambda: R04.post('/api/v1/receipts', json={
            'orderId': st['j7_order_id'], 'receiptDate': '2026-10-03', 'receiptAmount': 60000}))
        wo = r1['json']['item']['writeoffs']
        run.check('J8-收款核销第一期',
                  r1['status'] == 201 and len(wo) == 1 and wo[0]['amount'] == 60000
                  and bool(re.match(r'^SK\d{6}-\d{4}$', r1['json']['item']['receiptNo'])),
                  f"receipt → {r1['status']}, no={r1['json']['item'].get('receiptNo')}, 核销={wo}")

        # 收 40000 补足 → 全额,订单已完成(R02;P2 降级口径:回款即完成,开票条件留 S09 hook)
        r2 = try_call(lambda: R04.post('/api/v1/receipts', json={
            'orderId': st['j7_order_id'], 'receiptDate': '2026-10-03', 'receiptAmount': 40000}))
        done = try_call(lambda: R02.post(f"/api/v1/orders/{st['j7_order_id']}/status", json={'toStatus': '已完成'}))
        run.check('J8-全额回款订单已完成',
                  r2['status'] == 201 and done['json'].get('status') == '已完成',
                  f"补足 40000 → {r2['status']}; 完成 → {done['json'].get('status')}")

    api.step("J0'", '冒烟', j0)
    api.step('J1', '录入线索', j1)
    api.step('J2', '公海认领(互斥)', j2)
    api.step('J3', '跟进·联系人挂载', j3)
    api.step('J4', '转化(单向)+状态机边', j4)
    api.step('J5', '归属流转(留痕)', j5)
    api.step('J6', '商机阶段推进(S03)', j6)
    api.step('J7', '订单三源汇聚(S07)', j7)
    api.step('J8', '回款核销(S08)', j8)
    api.step('J9', '越权回归', j9)
