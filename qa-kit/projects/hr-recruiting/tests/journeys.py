# -*- coding: utf-8 -*-
"""hr-recruiting Phase 1 · Keel 穿行旅程(2026-10-04 提案版)

落点:Keel 项目空间 tests/journeys.py(本文件可直接 cp 覆盖)。
契约:同目录 hr-invariants.json(结构化不变量,42 条:confirmed 40 / draft 2),
  根文档《HR-契约不变量-20261004.json》为其同源副本。
方案:《HR-测试方案-20261004.md》(HR-J<段>-<三位> 用例体系)。

表面约定(与测试机框架实际签名不一致时,只改本文件顶部适配,步骤体不动):
  build_journey(api)         —— Keel journeys 注册入口
  api.as_role(key)           —— envAuth 装配的按角色客户端;键=演示手机号(见 envAuth 片段)
  api.step(段号, 标题, fn)   —— 注册一段;fn 签名 fn(run)
  run.check(名, bool, 证据)  —— 每条断言必须带证据文本;检查名即契约 left 锚点(journey:<段>/<检查名>.passed)

骨架 9+1 段:J0' 冒烟 + J1 岗位模板 + J2 用人需求 + J3 在招岗位 + J4 应聘初筛
  + J5 合规授权 + J6 面试执行 + J7 录用 offer + J8 合规台账 + J9 越权回归(10 段)。
断言零硬编码 id:全部先建后查、以响应返回值驱动;岗位/需求/候选人名按秒加后缀,旅程可重复执行。
日期口径:面试时间恒取「明天 10:00」;人才库超期样本「今天+400 天」(12 个月上限最长 366 天,恒超)、
  合法样本「今天+90 天」——不受运行日影响。

角色事实(同 crm 打法,均已 curl 实测):
  登录 POST /api/v1/auth/login {phone, password}(字段名是 phone,不是 username——Keel 客户端
    默认发 username 键会 400「手机号与密码必填」,envAuth 必须配 loginBody 模板映射,见下);
  token 12h(lib/auth.ts TOKEN_TTL),roleField=user.roleCode;
  演示账号 13800000001~06 / demo123 = R01 用人部门负责人(王建国,研发部)/ R02 HRBP(李慧敏)/
    R03 招聘专员(张晓琳)/ R04 业务面试官(赵一鸣)/ R05 招聘负责人(陈静怡)/ R06 系统管理员;
  health 在 /api/health(非 /api/v1/health),返回 {ok,name,version}。

envAuth 片段(建议,credentials 型 + P1 loginBody 模板):
  {"type":"credentials","path":"/api/v1/auth/login",
   "accounts":{"13800000001":{"username":"13800000001","password":"{env:HR_PWD}"}, ...06 同},
   "loginBody":{"phone":"{username}","password":"{password}"},
   "tokenField":"token","roleField":"user.roleCode",
   "roles":{"13800000001":"R01","13800000002":"R02","13800000003":"R03",
            "13800000004":"R04","13800000005":"R05","13800000006":"R06"}}

适配记录:
  2026-10-04 初版:try_call/_norm 双语义适配层照搬 crm-journeys.py(20261003 版);
    实测更正:offer 接受/拒绝真实路径为 /api/v1/interviews/decisions/:id/accept(路由挂在
    interviews 下,源码注释写的 /api/v1/decisions/... 与实际不符,journey 以实测路径为准)。
"""

import json
import re
import time
from datetime import date, timedelta

RESP = '负责穿行测试相关模块的设计与开发工作,支撑招聘全流程的稳定运行与迭代。'
ID_CARD = '110101199003077852'  # 18 位数字格式样本(服务端仅校验格式,不校验真伪)
A_PHONE = '13900000001'         # 候选人 A;脱敏断言依赖:maskPhone → '139****0001'
A_MASKED = '139****0001'


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
        # Keel 客户端把 {error:{code,message}} 拍平成顶层 {code,message} 时,此处还原外形
        js = {'error': js}
    if not isinstance(js, (dict, list)):
        # HR 列表接口返回裸 JSON 数组(与 CRM 的 {items:[]} 不同),list 须直通
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


def _d(days):
    return (date.today() + timedelta(days=days)).strftime('%Y-%m-%d')


def build_journey(api):
    st = {}  # 跨段数据总线(模板/需求/岗位/应聘/面试/决策 id、编号等),供后续段先建后查

    R01 = api.as_role('13800000001')  # 王建国 R01 用人部门负责人(研发部;提报/面试官/填面试结果)
    R02 = api.as_role('13800000002')  # 李慧敏 R02 HRBP(审核/应聘登记/初筛)
    R03 = api.as_role('13800000003')  # 张晓琳 R03 招聘专员(面试安排/offer 登记)
    R04 = api.as_role('13800000004')  # 赵一鸣 R04 业务面试官(面试官本人)
    R05 = api.as_role('13800000005')  # 陈静怡 R05 招聘负责人(决策/合规)
    R06 = api.as_role('13800000006')  # 系统管理员 R06(岗位模板主数据)

    st['ts'] = str(int(time.time()))[-6:]  # 秒级后缀:启用名唯一(409 规避)、旅程可重跑
    # users 列表不回 phone 字段,按 roleCode 映射 id(种子数据一角色恰好一人)
    users = try_call(lambda: R02.get('/api/v1/users'))['json']
    st['uid'] = {u['roleCode']: u['id'] for u in users}
    st['client_by_uid'] = {
        st['uid']['R01']: R01, st['uid']['R04']: R04, st['uid']['R05']: R05,
    }
    tomorrow = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')

    # 通用构造:提报并审核通过,返回在招岗位列表(lines 直接内联明细,不引用模板)
    def _mk_positions(tag, headcount, applicant, auditor, job_name=None):
        body = {
            'summary': f'KEEL需求{st["ts"]}{tag}', 'demandDept': '研发部',
            'lines': [{'jobName': job_name or f'KEEL岗位{tag}{st["ts"]}', 'recruitType': '社会招聘',
                       'responsibilities': RESP, 'headcount': headcount, 'urgency': '一般',
                       'startDate': _d(0)}],
        }
        r = try_call(lambda: applicant.post('/api/v1/hiring-requests', json=body))
        rid = r['json']['id']
        d = try_call(lambda: auditor.post(f'/api/v1/hiring-requests/{rid}/audit', json={'action': 'APPROVE'}))
        return rid, d['json'].get('createdPositions', [])

    # 通用构造:应聘登记 → 初筛转面试 → 面试邀约 → 面试结果(通过/不通过)
    def _chain(tag, pos, itv_uid, passed=True):
        st['phone_seq'] = st.get('phone_seq', 0) + 1
        ph = f'139{st["ts"]}{st["phone_seq"]:02d}'  # 139+秒缀+序号=11 位,链间互异、可重跑
        a = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人{tag}{st["ts"]}', 'phone': ph, 'positionId': pos,
            'channel': '官方网站', 'consentObtained': True, 'retentionConsent': True}))
        aid = a['json']['id']
        try_call(lambda: R02.post(f'/api/v1/applications/{aid}/screenings', json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '用人部门评估',
            'deptContactId': st["uid"]["R01"]}))
        itv = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': aid, 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewTime': f'{tomorrow} 10:00', 'interviewerId': itv_uid,
            'interviewMethod': '视频面试', 'interviewType': '业务面试',
            'interviewAddr': f'https://meet.example.com/{tag}-{st["ts"]}'}))
        iid = itv['json']['id']
        client = st['client_by_uid'][itv_uid]
        try_call(lambda: client.post(f'/api/v1/interviews/{iid}/result', json={
            'interviewResult': '面试通过' if passed else '暂不考虑',
            'interviewNote': f'穿行链{tag}面试评语:候选人表达清晰,专业匹配度高,流程记录完整无歧义。'
            if passed else f'穿行链{tag}面试评语:候选人与岗位要求存在差距,本次不作推进,留档备查。'}))
        return {'apply': aid, 'interview': iid}

    # ---------- J0' 冒烟 ----------
    def j0(run):
        r = try_call(lambda: R02.get('/api/v1/job-templates'))
        run.check("J0-冒烟模板列表200", r['status'] == 200, f"GET /api/v1/job-templates → {r['status']}")

    # ---------- J1 岗位模板建档与维护(S01) ----------
    def j1(run):
        tpl_body = {'jobName': f'KEEL岗位主{st["ts"]}', 'recruitType': '社会招聘',
                    'responsibilities': RESP, 'requirements': '本科及以上,三年相关经验',
                    'salaryRange': '20-30K', 'keywords': '穿行,测试'}
        r = try_call(lambda: R06.post('/api/v1/job-templates', json=tpl_body))
        tpl = r['json']
        st['tpl_id'] = tpl.get('id')
        st['tpl_name'] = tpl_body['jobName']
        run.check('J1-建档201含POS编号',
                  r['status'] == 201 and bool(re.match(r'^POS-\d{8}-\d{4}$', tpl.get('jobCode', ''))),
                  f"POST /api/v1/job-templates → {r['status']}, jobCode={tpl.get('jobCode')}")

        bad1 = try_call(lambda: R06.post('/api/v1/job-templates', json={'jobName': 'X', 'recruitType': '社会招聘'}))
        bad2 = try_call(lambda: R06.post('/api/v1/job-templates', json={
            'jobName': f'KEEL岗位短{st["ts"]}', 'recruitType': '社会招聘', 'responsibilities': '职责不足二十字'}))
        bad3 = try_call(lambda: R06.post('/api/v1/job-templates', json={
            'jobName': f'KEEL岗位类{st["ts"]}', 'recruitType': '猎头招聘', 'responsibilities': RESP}))
        run.check('J1-必填与枚举校验400',
                  bad1['status'] == 400 and bad2['status'] == 400 and bad3['status'] == 400,
                  f"缺职责→{bad1['status']}; 职责<20字→{bad2['status']}; 非法招聘类型→{bad3['status']}")

        disc = try_call(lambda: R06.post('/api/v1/job-templates', json={
            'jobName': f'KEEL岗位歧{st["ts"]}', 'recruitType': '社会招聘', 'responsibilities': RESP,
            'requirements': '限男性,能适应高强度加班'}))
        run.check('J1-反歧视阻断400',
                  disc['status'] == 400 and disc['json'].get('error', {}).get('code') == 'DISCRIMINATORY_WORD',
                  f"任职条件含「限男性」→ {disc['status']}, code={disc['json'].get('error', {}).get('code')}")

        dup = try_call(lambda: R06.post('/api/v1/job-templates', json=tpl_body))
        run.check('J1-同启用名重复409',
                  dup['status'] == 409 and dup['json'].get('error', {}).get('code') == 'JOB_NAME_EXISTS',
                  f"同启用名再建 → {dup['status']}, code={dup['json'].get('error', {}).get('code')}")

        rbac = try_call(lambda: R03.post('/api/v1/job-templates', json=tpl_body))
        run.check('J1-R03无建档权限403', rbac['status'] == 403, f"R03 建档 → {rbac['status']}")

        l3 = try_call(lambda: R03.get('/api/v1/job-templates'))
        row3 = next((i for i in l3['json'] if i.get('id') == st['tpl_id']), {})
        l2 = try_call(lambda: R02.get('/api/v1/job-templates'))
        row2 = next((i for i in l2['json'] if i.get('id') == st['tpl_id']), {})
        run.check('J1-薪酬按角色脱敏',
                  row3.get('salaryRange') is None and row3.get('salaryHidden') is True
                  and row2.get('salaryRange') == '20-30K',
                  f"R03 salaryRange={row3.get('salaryRange')}/hidden={row3.get('salaryHidden')}; "
                  f"R02 salaryRange={row2.get('salaryRange')}")

        new_name = st['tpl_name'] + '改'
        up = try_call(lambda: R06.put(f"/api/v1/job-templates/{st['tpl_id']}", json={'jobName': new_name}))
        logs = try_call(lambda: R06.get(f"/api/v1/job-templates/{st['tpl_id']}/change-logs"))
        has_log = any(g.get('fieldName') == 'job_name' for g in logs['json'])
        run.check('J1-编辑留痕change-logs', up['status'] == 200 and has_log,
                  f"PUT → {up['status']}; change-logs job_name 记录存在={has_log}")
        st['tpl_name'] = new_name

    # ---------- J2 用人需求提报与审核转在招(S02) ----------
    def j2(run):
        # 主链 REQ-A:R01 提报(引用 J1 模板,headcount=2 留足录用位);REQ-B:R02 代提(内联明细)
        ra = try_call(lambda: R01.post('/api/v1/hiring-requests', json={
            'summary': f'KEEL主链需求{st["ts"]}', 'demandDept': '研发部',
            'lines': [{'jobTemplateId': st['tpl_id'], 'headcount': 2, 'urgency': '紧急',
                       'startDate': _d(0)}]}))
        st['req_a'] = ra['json'].get('id')
        run.check('J2-提报201待审核',
                  ra['status'] == 201 and bool(re.match(r'^REQ-\d{8}-\d{4}$', ra['json'].get('requestNo', ''))),
                  f"POST /api/v1/hiring-requests → {ra['status']}, requestNo={ra['json'].get('requestNo')}")
        da = try_call(lambda: R01.get(f"/api/v1/hiring-requests/{st['req_a']}"))
        st['req_a_snapshot_name'] = (da['json'].get('lines') or [{}])[0].get('jobName')
        run.check('J2-模板快照带出',
                  da['json'].get('status') == '待审核' and st['req_a_snapshot_name'] == st['tpl_name'],
                  f"status={da['json'].get('status')}, line jobName={st['req_a_snapshot_name']}(模板名)")

        rb = try_call(lambda: R02.post('/api/v1/hiring-requests', json={
            'summary': f'KEEL代提需求{st["ts"]}', 'demandDept': '研发部',
            'lines': [{'jobName': f'KEEL岗位B{st["ts"]}', 'recruitType': '社会招聘',
                       'responsibilities': RESP, 'headcount': 1, 'urgency': '一般',
                       'startDate': _d(0)}]}))
        st['req_b'] = rb['json'].get('id')
        sep1 = try_call(lambda: R02.post(f"/api/v1/hiring-requests/{st['req_b']}/audit", json={'action': 'APPROVE'}))
        sep2 = try_call(lambda: R01.post(f"/api/v1/hiring-requests/{st['req_a']}/audit", json={'action': 'APPROVE'}))
        run.check('J2-岗位分离(自审403·无权限403)',
                  sep1['status'] == 403 and sep2['status'] == 403,
                  f"R02 审本人代提 → {sep1['status']}; R01 审(无 hiring:audit)→ {sep2['status']}")

        rej_short = try_call(lambda: R05.post(f"/api/v1/hiring-requests/{st['req_b']}/audit",
                                              json={'action': 'REJECT', 'comment': '不同意'}))
        rej = try_call(lambda: R05.post(f"/api/v1/hiring-requests/{st['req_b']}/audit",
                                        json={'action': 'REJECT', 'comment': '本期编制已满,暂缓招聘'}))
        drb = try_call(lambda: R05.get(f"/api/v1/hiring-requests/{st['req_b']}"))
        run.check('J2-拒绝原因校验转已拒绝',
                  rej_short['status'] == 400 and rej['json'].get('status') == '已拒绝'
                  and drb['json'].get('status') == '已拒绝',
                  f"4字原因 → {rej_short['status']}; 合规拒绝 → {rej['json'].get('status')}")

        resub = try_call(lambda: R02.put(f"/api/v1/hiring-requests/{st['req_b']}", json={
            'summary': f'KEEL代提需求{st["ts"]}(修订)', 'demandDept': '研发部',
            'lines': [{'jobName': f'KEEL岗位B{st["ts"]}', 'recruitType': '社会招聘',
                       'responsibilities': RESP, 'headcount': 1, 'urgency': '一般',
                       'startDate': _d(0)}]}))
        run.check('J2-修改重提回待审核', resub['json'].get('status') == '待审核',
                  f"PUT 重提 → status={resub['json'].get('status')}")

        app_a = try_call(lambda: R02.post(f"/api/v1/hiring-requests/{st['req_a']}/audit",
                                          json={'action': 'APPROVE', 'comment': '同意'}))
        app_b = try_call(lambda: R05.post(f"/api/v1/hiring-requests/{st['req_b']}/audit",
                                          json={'action': 'APPROVE'}))
        pos_a = (app_a['json'].get('createdPositions') or [{}])[0]
        pos_b = (app_b['json'].get('createdPositions') or [{}])[0]
        st['pos_main'] = pos_a.get('id')
        st['pos_p2'] = pos_b.get('id')
        run.check('J2-通过转在招生成OP',
                  app_a['json'].get('status') == '已转在招'
                  and bool(re.match(r'^OP-\d{8}-\d{4}$', pos_a.get('positionNo', '')))
                  and app_b['json'].get('status') == '已转在招',
                  f"REQ-A → {app_a['json'].get('status')}, {pos_a.get('positionNo')}; "
                  f"REQ-B → {app_b['json'].get('status')}, {pos_b.get('positionNo')}")

        l1 = try_call(lambda: R01.get('/api/v1/hiring-requests'))
        ids1 = [i['id'] for i in l1['json']]
        run.check('J2-R01列表仅本人',
                  st['req_a'] in ids1 and st['req_b'] not in ids1,
                  f"R01 列表含本人 REQ-A={st['req_a'] in ids1}, 含 R02 代提 REQ-B={st['req_b'] in ids1}")

    # ---------- J3 在招岗位维护与状态变更(S02-003/004;用 REQ-B 的 P2) ----------
    def j3(run):
        pid = st['pos_p2']
        ro = try_call(lambda: R03.put(f'/api/v1/open-positions/{pid}', json={'positionStatus': '已关闭'}))
        run.check('J3-状态字段只读400',
                  ro['status'] == 400 and ro['json'].get('error', {}).get('code') == 'STATUS_IMMUTABLE',
                  f"PUT positionStatus → {ro['status']}, code={ro['json'].get('error', {}).get('code')}")

        h0 = try_call(lambda: R03.put(f'/api/v1/open-positions/{pid}', json={'headcount': 0}))
        short = try_call(lambda: R02.post(f'/api/v1/open-positions/{pid}/status',
                                          json={'toStatus': '已关闭', 'reason': '不要了'}))
        run.check('J3-维护校验400',
                  h0['status'] == 400 and short['status'] == 400,
                  f"headcount=0 → {h0['status']}; 关闭原因4字(R02)→ {short['status']}")

        close = try_call(lambda: R02.post(f'/api/v1/open-positions/{pid}/status',
                                          json={'toStatus': '已关闭', 'reason': '穿行验证人工关闭,编制回收'}))
        d = try_call(lambda: R02.get(f'/api/v1/open-positions/{pid}'))
        log = (d['json'].get('statusLogs') or [{}])[0]
        run.check('J3-关闭200留痕',
                  close['status'] == 200 and d['json'].get('positionStatus') == '已关闭'
                  and log.get('toStatus') == '已关闭' and log.get('isAuto') is False,
                  f"关闭 → {close['status']}; 详情={d['json'].get('positionStatus')}; 留痕 isAuto={log.get('isAuto')}")

        again = try_call(lambda: R02.post(f'/api/v1/open-positions/{pid}/status',
                                          json={'toStatus': '已关闭', 'reason': '穿行验证同状态重复关闭'}))
        run.check('J3-同状态409',
                  again['status'] == 409 and again['json'].get('error', {}).get('code') == 'STATUS_UNCHANGED',
                  f"重复关闭 → {again['status']}, code={again['json'].get('error', {}).get('code')}")

        reopen = try_call(lambda: R02.post(f'/api/v1/open-positions/{pid}/status',
                                           json={'toStatus': '招聘中', 'reason': '穿行验证重开'}))
        d2 = try_call(lambda: R02.get(f'/api/v1/open-positions/{pid}'))
        reclose = try_call(lambda: R02.post(f'/api/v1/open-positions/{pid}/status',
                                            json={'toStatus': '已关闭', 'reason': '穿行验证完毕,回收测试岗位'}))
        d3 = try_call(lambda: R02.get(f'/api/v1/open-positions/{pid}'))
        run.check('J3-重开200回招聘中',
                  reopen['status'] == 200 and d2['json'].get('positionStatus') == '招聘中'
                  and reclose['status'] == 200 and d3['json'].get('positionStatus') == '已关闭',
                  f"重开 → {reopen['status']}/{d2['json'].get('positionStatus')}; "
                  f"复关 → {reclose['status']}/{d3['json'].get('positionStatus')}(终态已关闭,供 J4 拒投断言)")

    # ---------- J4 候选人申请与 HR 初筛(S03;主岗 P_main) ----------
    def j4(run):
        closed_reject = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人Z{st["ts"]}', 'phone': '13899990001', 'positionId': st['pos_p2'],
            'channel': '官方网站', 'consentObtained': True, 'retentionConsent': True}))
        run.check('J4-岗位关闭拒收', closed_reject['status'] == 400,
                  f"向已关闭岗位投递 → {closed_reject['status']}")

        c1 = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人A{st["ts"]}', 'phone': A_PHONE, 'positionId': st['pos_main'],
            'channel': '官方网站'}))
        c2 = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人A{st["ts"]}', 'phone': A_PHONE, 'positionId': st['pos_main'],
            'channel': '官方网站', 'consentObtained': True}))
        run.check('J4-同意闸门400',
                  c1['status'] == 400 and c1['json'].get('error', {}).get('code') == 'CONSENT_REQUIRED'
                  and c2['status'] == 400,
                  f"缺处理同意 → {c1['status']}/{c1['json'].get('error', {}).get('code')}; "
                  f"缺留存同意 → {c2['status']}")

        a = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人A{st["ts"]}', 'phone': A_PHONE, 'positionId': st['pos_main'],
            'channel': '官方网站', 'consentObtained': True, 'retentionConsent': True,
            'idCard': ID_CARD, 'email': 'keel-a@example.com',
            'birthDate': '1990-03-07'}))
        st['app_a'] = a['json'].get('id')
        da = try_call(lambda: R02.get(f"/api/v1/applications/{st['app_a']}"))
        run.check('J4-登记201含APP编号',
                  a['status'] == 201 and bool(re.match(r'^APP-\d{8}-\d{4}$', a['json'].get('applyNo', '')))
                  and da['json'].get('status') == '待初筛',
                  f"POST /api/v1/applications → {a['status']}, applyNo={a['json'].get('applyNo')}, "
                  f"初态={da['json'].get('status')}")

        w1 = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人W{st["ts"]}', 'phone': '13899990002', 'positionId': st['pos_main'],
            'channel': '招聘网站', 'consentObtained': True, 'retentionConsent': True}))
        w2 = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人W{st["ts"]}', 'phone': '13899990002', 'positionId': st['pos_main'],
            'channel': '内部推荐', 'referrerName': '不存在人', 'referrerNo': 'E9999',
            'consentObtained': True, 'retentionConsent': True}))
        w3 = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人W{st["ts"]}', 'phone': '13899990002', 'positionId': st['pos_main'],
            'channel': '人才库', 'consentObtained': True, 'retentionConsent': True}))
        run.check('J4-渠道条件必填400',
                  w1['status'] == 400 and w2['status'] == 400 and w3['status'] == 400,
                  f"招聘网站未选站 → {w1['status']}; 内推无效工号 → {w2['status']}; "
                  f"人才库渠道(Phase 2)→ {w3['status']}")

        lst = try_call(lambda: R02.get(f"/api/v1/applications?positionId={st['pos_main']}"))
        row = next((i for i in lst['json'] if i.get('id') == st['app_a']), {})
        run.check('J4-列表服务端脱敏',
                  row.get('phone') == A_MASKED and row.get('idCardMasked', '').startswith('110')
                  and row.get('idCardMasked', '').endswith('7852') and ID_CARD not in str(lst['json']),
                  f"phone={row.get('phone')}, idCardMasked={row.get('idCardMasked')}, 明文未下发={ID_CARD not in str(lst['json'])}")

        scope4 = try_call(lambda: R04.get('/api/v1/applications'))
        run.check('J4-R04仅见已转面试',
                  all(i.get('id') != st['app_a'] for i in scope4['json']),
                  f"R04 列表含未转面试的 A={any(i.get('id') == st['app_a'] for i in scope4['json'])}")

        # 淘汰语义(独立候选人 X,淘汰后供 J5 人才库授权)
        x = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人X{st["ts"]}', 'phone': '13899990003', 'positionId': st['pos_main'],
            'channel': '官方网站', 'consentObtained': True, 'retentionConsent': True}))
        st['app_x'] = x['json'].get('id')
        x1 = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '暂不考虑', 'reason': '经验不足'}))
        x2 = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '暂不考虑', 'reason': '女性优先不考虑'}))
        x3 = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '暂不考虑',
            'reason': '当前岗位匹配度不足,暂不推进'}))
        dx = try_call(lambda: R02.get(f"/api/v1/applications/{st['app_x']}"))
        run.check('J4-淘汰原因与反歧视',
                  x1['status'] == 400 and x2['status'] == 400 and x3['json'].get('status') == '已淘汰'
                  and dx['json'].get('status') == '已淘汰',
                  f"4字原因 → {x1['status']}; 歧视表述 → {x2['status']}; 合规淘汰 → {x3['json'].get('status')}")

        s1 = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_a']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '用人部门评估'}))
        s2 = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_a']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '用人部门评估',
            'deptContactId': st["uid"]["R01"]}))
        da2 = try_call(lambda: R02.get(f"/api/v1/applications/{st['app_a']}"))
        run.check('J4-转面试须对接人',
                  s1['status'] == 400 and s2['json'].get('status') == '已转面试'
                  and da2['json'].get('status') == '已转面试',
                  f"无对接人 → {s1['status']}; 带 R01 对接人 → {s2['json'].get('status')}")

        locked = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_a']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '继续沟通'}))
        run.check('J4-初筛关闭409',
                  locked['status'] == 409 and locked['json'].get('error', {}).get('code') == 'SCREENING_CLOSED',
                  f"已转面试再初筛 → {locked['status']}, code={locked['json'].get('error', {}).get('code')}")

        rbac4 = try_call(lambda: R04.post(f"/api/v1/applications/{st['app_a']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '继续沟通'}))
        run.check('J4-R04无初筛权限403', rbac4['status'] == 403, f"R04 初筛 → {rbac4['status']}")

        # 候选人 B:继续沟通 → 初筛中(J5 授权 409 样本 / J8 删除权样本)
        b = try_call(lambda: R02.post('/api/v1/applications', json={
            'name': f'KEEL候选人B{st["ts"]}', 'phone': '13899990004', 'positionId': st['pos_main'],
            'channel': '官方网站', 'consentObtained': True, 'retentionConsent': True}))
        st['app_b'] = b['json'].get('id')
        sb = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_b']}/screenings", json={
            'contactAt': _d(0), 'contactType': '电话沟通', 'result': '继续沟通'}))
        run.check('J4-继续沟通转初筛中', sb['json'].get('status') == '初筛中',
                  f"B 初筛 → {sb['json'].get('status')}")

    # ---------- J5 合规:敏感查看与人才库授权(S03-004/006) ----------
    def j5(run):
        sv = try_call(lambda: R05.post(f"/api/v1/applications/{st['app_a']}/sensitive-view",
                                       json={'reason': 'KEEL穿行验证敏感信息二次授权'}))
        logs = try_call(lambda: R05.get(f"/api/v1/compliance/access-logs?applyId={st['app_a']}"))
        run.check('J5-敏感查看明文与留痕',
                  sv['status'] == 200 and sv['json'].get('idCard') == ID_CARD
                  and any(l.get('applyId') == st['app_a'] for l in logs['json']),
                  f"R05 sensitive-view → {sv['status']}, idCard 还原={sv['json'].get('idCard') == ID_CARD}, "
                  f"访问日志条数={len(logs['json'])}")

        no = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_a']}/sensitive-view",
                                       json={'reason': 'KEEL穿行验证非授权角色'}))
        short = try_call(lambda: R05.post(f"/api/v1/applications/{st['app_a']}/sensitive-view",
                                          json={'reason': '太短'}))
        run.check('J5-非R05与理由校验',
                  no['status'] == 403 and short['status'] == 400,
                  f"R02 敏感查看 → {no['status']}; 理由2字 → {short['status']}")

        over = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/talent-pool-consent", json={
            'consentPurpose': 'KEEL穿行验证授权期限上限', 'consentChannel': '系统勾选',
            'validUntil': _d(400)}))
        run.check('J5-授权超12月400',
                  over['status'] == 400 and '12 个月' in str(over['json'].get('error', {}).get('message', '')),
                  f"今天+400 天 → {over['status']}, message={over['json'].get('error', {}).get('message')}")

        early = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_b']}/talent-pool-consent", json={
            'consentPurpose': 'KEEL穿行验证初筛未结束', 'consentChannel': '系统勾选',
            'validUntil': _d(90)}))
        run.check('J5-初筛未结束409',
                  early['status'] == 409 and early['json'].get('error', {}).get('code') == 'SCREENING_NOT_CLOSED',
                  f"B(初筛中)授权 → {early['status']}, code={early['json'].get('error', {}).get('code')}")

        ok = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/talent-pool-consent", json={
            'consentPurpose': 'KEEL穿行验证合法授权样本', 'consentChannel': '邮件', 'validUntil': _d(90)}))
        dup = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/talent-pool-consent", json={
            'consentPurpose': 'KEEL穿行验证重复授权', 'consentChannel': '邮件', 'validUntil': _d(90)}))
        rv = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/talent-pool-consent/revoke"))
        rv2 = try_call(lambda: R02.post(f"/api/v1/applications/{st['app_x']}/talent-pool-consent/revoke"))
        run.check('J5-授权成功与撤回',
                  ok['status'] == 201 and ok['json'].get('toTalentPool') is True
                  and dup['status'] == 409 and rv['status'] == 200 and rv2['status'] == 404,
                  f"授权(+90天) → {ok['status']}; 重复 → {dup['status']}; 撤回 → {rv['status']}; "
                  f"再撤回 → {rv2['status']}")

    # ---------- J6 面试邀约与执行(S04-001/002) ----------
    def j6(run):
        notin = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_b'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewTime': f'{tomorrow} 10:00', 'interviewerId': st["uid"]["R04"],
            'interviewMethod': '视频面试', 'interviewType': '业务面试', 'interviewAddr': 'https://x.example.com/1'}))
        run.check('J6-仅初筛通过可邀约409',
                  notin['status'] == 409 and notin['json'].get('error', {}).get('code') == 'NOT_SCREENED_IN',
                  f"B(初筛中)邀约 → {notin['status']}, code={notin['json'].get('error', {}).get('code')}")

        off = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_a'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': 'offer流程'}))
        notime = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_a'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewerId': st["uid"]["R04"], 'interviewMethod': '视频面试',
            'interviewType': '业务面试', 'interviewAddr': 'https://x.example.com/2'}))
        past = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_a'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewTime': '2020-01-01 09:00', 'interviewerId': st["uid"]["R04"],
            'interviewMethod': '视频面试', 'interviewType': '业务面试', 'interviewAddr': 'https://x.example.com/3'}))
        badiv = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_a'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewTime': f'{tomorrow} 10:00', 'interviewerId': st["uid"]["R03"],
            'interviewMethod': '视频面试', 'interviewType': '业务面试', 'interviewAddr': 'https://x.example.com/4'}))
        run.check('J6-邀约条件校验400',
                  off['status'] == 400 and notime['status'] == 400 and past['status'] == 400 and badiv['status'] == 400,
                  f"offer流程 → {off['status']}; 缺时间 → {notime['status']}; 过去时间 → {past['status']}; "
                  f"面试官=R03 → {badiv['status']}")

        itv = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_a'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewTime': f'{tomorrow} 10:00', 'interviewerId': st["uid"]["R04"],
            'interviewMethod': '视频面试', 'interviewType': '业务面试',
            'interviewAddr': f'https://meet.example.com/main-{st["ts"]}'}))
        st['itv_a'] = itv['json'].get('id')
        run.check('J6-已安排201含ITV编号',
                  itv['status'] == 201 and itv['json'].get('status') == '已安排'
                  and bool(re.match(r'^ITV-\d{8}-\d{4}$', itv['json'].get('interviewNo', ''))),
                  f"POST /api/v1/interviews → {itv['status']}, no={itv['json'].get('interviewNo')}, "
                  f"status={itv['json'].get('status')}")

        dup = try_call(lambda: R03.post('/api/v1/interviews', json={
            'applyId': st['app_a'], 'contactAt': _d(0), 'contactType': '电话沟通', 'nextStep': '面试流程',
            'interviewTime': f'{tomorrow} 11:00', 'interviewerId': st["uid"]["R01"],
            'interviewMethod': '视频面试', 'interviewType': '总监面试', 'interviewAddr': 'https://x.example.com/5'}))
        run.check('J6-进行中唯一409',
                  dup['status'] == 409 and dup['json'].get('error', {}).get('code') == 'INTERVIEW_EXISTS',
                  f"重复邀约 → {dup['status']}, code={dup['json'].get('error', {}).get('code')}")

        s1 = try_call(lambda: R04.post(f"/api/v1/interviews/{st['itv_a']}/start"))
        s2 = try_call(lambda: R04.post(f"/api/v1/interviews/{st['itv_a']}/start"))
        run.check('J6-开始面试',
                  s1['json'].get('status') == '面试中' and s2['status'] == 409,
                  f"start → {s1['json'].get('status')}; 再 start → {s2['status']}")

        other = try_call(lambda: R01.post(f"/api/v1/interviews/{st['itv_a']}/result", json={
            'interviewResult': '面试通过', 'interviewNote': '非本人填写的结果应当被服务端拒绝,此评语超过二十字。'}))
        run.check('J6-结果仅本人403', other['status'] == 403, f"R01(有权限点,非本人)→ {other['status']}")

        shortn = try_call(lambda: R04.post(f"/api/v1/interviews/{st['itv_a']}/result", json={
            'interviewResult': '面试通过', 'interviewNote': '评语不足二十字。'}))
        ok = try_call(lambda: R04.post(f"/api/v1/interviews/{st['itv_a']}/result", json={
            'interviewResult': '面试通过',
            'interviewNote': '穿行主链面试评语:候选人系统设计扎实,沟通顺畅,与岗位要求匹配,建议推进。'}))
        lock = try_call(lambda: R04.post(f"/api/v1/interviews/{st['itv_a']}/result", json={
            'interviewResult': '面试通过', 'interviewNote': '重复提交的结果应当被锁定拒绝,此评语超过二十字。'}))
        run.check('J6-评语校验与锁定409',
                  shortn['status'] == 400 and ok['json'].get('status') == '已完成' and lock['status'] == 409
                  and lock['json'].get('error', {}).get('code') == 'RESULT_LOCKED',
                  f"评语8字 → {shortn['status']}; 提交 → {ok['json'].get('status')}; "
                  f"重复 → {lock['status']}/{lock['json'].get('error', {}).get('code')}")

        rv = try_call(lambda: R05.post(f"/api/v1/interviews/{st['itv_a']}/revoke-result",
                                       json={'reason': 'KEEL穿行验证撤销重填链路'}))
        refil = try_call(lambda: R04.post(f"/api/v1/interviews/{st['itv_a']}/result", json={
            'interviewResult': '面试通过',
            'interviewNote': '撤销后重填的面试评语:候选人整体表现符合预期,维持通过结论,记录完整。'}))
        run.check('J6-R05撤销重填',
                  rv['json'].get('status') == '面试中' and refil['json'].get('status') == '已完成',
                  f"revoke → {rv['json'].get('status')}; 重填 → {refil['json'].get('status')}")

    # ---------- J7 录用决策与 offer(S04-003;C/D/E/F 四条辅链) ----------
    def j7(run):
        r04uid = st["uid"]["R04"]
        r01uid = st["uid"]["R01"]
        r05uid = st["uid"]["R05"]

        # F 链:面试「暂不考虑」(面试官 R01,R05 决策)→ 不可进入录用决策 409
        f = _chain('F', st['pos_main'], r01uid, passed=False)
        notpassed = try_call(lambda: R05.post(f"/api/v1/interviews/{f['interview']}/decision",
                                              json={'decision': '录用', 'offerSalary': '25K', 'offerLevel': 'P6',
                                                    'offerDate': _d(2), 'onboardDate': _d(30)}))
        # F2 链:面试官=R05 本人(有 offer:decide)→ 路由级岗位分离 403「不能决策本人面试的候选人」
        f2 = _chain('F2', st['pos_main'], r05uid)
        sep = try_call(lambda: R05.post(f"/api/v1/interviews/{f2['interview']}/decision",
                                        json={'decision': '录用', 'offerSalary': '25K', 'offerLevel': 'P6',
                                              'offerDate': _d(2), 'onboardDate': _d(30)}))
        run.check('J7-岗位分离与前置403/409',
                  notpassed['status'] == 409 and notpassed['json'].get('error', {}).get('code') == 'NOT_INTERVIEW_PASSED'
                  and sep['status'] == 403,
                  f"对「暂不考虑」决策 → {notpassed['status']}/{notpassed['json'].get('error', {}).get('code')}; "
                  f"决策人=面试官(R05)→ {sep['status']}")

        lack = try_call(lambda: R05.post(f"/api/v1/interviews/{st['itv_a']}/decision", json={'decision': '录用'}))
        dec = try_call(lambda: R05.post(f"/api/v1/interviews/{st['itv_a']}/decision", json={
            'decision': '录用', 'offerSalary': '25K', 'offerLevel': 'P6',
            'offerDate': _d(2), 'onboardDate': _d(30)}))
        dup = try_call(lambda: R05.post(f"/api/v1/interviews/{st['itv_a']}/decision", json={
            'decision': '录用', 'offerSalary': '26K', 'offerLevel': 'P6',
            'offerDate': _d(2), 'onboardDate': _d(30)}))
        run.check('J7-录用必填与offer已发',
                  lack['status'] == 400 and dec['json'].get('decisionStatus') == 'offer已发' and dup['status'] == 409,
                  f"缺定薪 → {lack['status']}; 决策 → {dec['json'].get('decisionStatus')}; "
                  f"重复决策 → {dup['status']}")
        st['dec_a'] = try_call(lambda: R02.get(f"/api/v1/interviews/{st['itv_a']}"))['json'].get('decision', {}).get('id')

        acc1 = try_call(lambda: R03.post(f"/api/v1/interviews/decisions/{st['dec_a']}/accept"))
        accdup = try_call(lambda: R03.post(f"/api/v1/interviews/decisions/{st['dec_a']}/accept"))
        d1 = try_call(lambda: R02.get(f"/api/v1/open-positions/{st['pos_main']}"))
        run.check('J7-accept回写未满员',
                  acc1['json'].get('decisionStatus') == '已录用' and acc1['json'].get('hiredCount') == 1
                  and acc1['json'].get('positionClosed') is False and accdup['status'] == 409
                  and d1['json'].get('positionStatus') == '招聘中',
                  f"accept → hired={acc1['json'].get('hiredCount')}, closed={acc1['json'].get('positionClosed')}; "
                  f"重复 accept → {accdup['status']}; 岗位仍 {d1['json'].get('positionStatus')}")

        # C/D/E 三条辅链在岗位关闭前完成到「面试通过」
        c = _chain('C', st['pos_main'], r01uid)
        dch = _chain('D', st['pos_main'], r01uid)
        e = _chain('E', st['pos_main'], r01uid)
        st['chain_c'], st['chain_d'], st['chain_e'] = c, dch, e

        dc = try_call(lambda: R05.post(f"/api/v1/interviews/{c['interview']}/decision", json={
            'decision': '录用', 'offerSalary': '22K', 'offerLevel': 'P5',
            'offerDate': _d(2), 'onboardDate': _d(30)}))
        # decision 接口返回体里的 id 是面试 id,accept 用的 decision.id 需经详情回读
        dec_c = try_call(lambda: R02.get(f"/api/v1/interviews/{c['interview']}"))['json'].get('decision', {})
        accc = try_call(lambda: R03.post(f"/api/v1/interviews/decisions/{dec_c.get('id')}/accept"))
        d2 = try_call(lambda: R02.get(f"/api/v1/open-positions/{st['pos_main']}"))
        log2 = (d2['json'].get('statusLogs') or [{}])[0]
        run.check('J7-招满自动关闭is_auto',
                  accc['json'].get('hiredCount') == 2 and accc['json'].get('positionClosed') is True
                  and d2['json'].get('positionStatus') == '已关闭' and log2.get('isAuto') is True
                  and log2.get('operatorName') == '系统',
                  f"accept#2 → hired={accc['json'].get('hiredCount')}, closed={accc['json'].get('positionClosed')}; "
                  f"岗位={d2['json'].get('positionStatus')}; 留痕 isAuto={log2.get('isAuto')}, 操作人={log2.get('operatorName')}")

        dd = try_call(lambda: R05.post(f"/api/v1/interviews/{dch['interview']}/decision", json={
            'decision': '录用', 'offerSalary': '22K', 'offerLevel': 'P5',
            'offerDate': _d(2), 'onboardDate': _d(30)}))
        dec_d = try_call(lambda: R02.get(f"/api/v1/interviews/{dch['interview']}"))['json'].get('decision', {})
        rej = try_call(lambda: R03.post(f"/api/v1/interviews/decisions/{dec_d.get('id')}/reject-offer"))
        d3 = try_call(lambda: R02.get(f"/api/v1/open-positions/{st['pos_main']}"))
        run.check('J7-拒绝offer不加人数',
                  rej['json'].get('decisionStatus') == '已结束' and d3['json'].get('hiredCount') == 2,
                  f"reject-offer → {rej['json'].get('decisionStatus')}; hiredCount 仍={d3['json'].get('hiredCount')}")

        de = try_call(lambda: R05.post(f"/api/v1/interviews/{e['interview']}/decision", json={
            'decision': '录用', 'offerSalary': '22K', 'offerLevel': 'P5',
            'offerDate': _d(2), 'onboardDate': _d(30)}))
        dec_e = try_call(lambda: R02.get(f"/api/v1/interviews/{e['interview']}"))['json'].get('decision', {})
        acce = try_call(lambda: R03.post(f"/api/v1/interviews/decisions/{dec_e.get('id')}/accept"))
        run.check('J7-已关岗位accept409',
                  acce['status'] == 409 and acce['json'].get('error', {}).get('code') == 'POSITION_CLOSED',
                  f"岗位已关闭再 accept → {acce['status']}, code={acce['json'].get('error', {}).get('code')}")

        frozen = try_call(lambda: R03.put(f"/api/v1/open-positions/{st['pos_main']}",
                                          json={'jobName': f'KEEL改名尝试{st["ts"]}'}))
        run.check('J7-有关联候选人名称冻结409',
                  frozen['status'] == 409 and frozen['json'].get('error', {}).get('code') == 'JOB_NAME_FROZEN',
                  f"PUT jobName → {frozen['status']}, code={frozen['json'].get('error', {}).get('code')}")

    # ---------- J8 合规台账与权利请求(S03-006) ----------
    def j8(run):
        led = try_call(lambda: R05.get('/api/v1/compliance/ledgers'))
        row = next((i for i in led['json'] if i.get('applyId') == st['app_a']), {})
        led3 = try_call(lambda: R03.get('/api/v1/compliance/ledgers'))
        run.check('J8-台账权限与留痕',
                  led['status'] == 200 and bool(row) and led3['status'] == 403,
                  f"R05 台账 → {led['status']}, A 的台账存在={bool(row)}; R03 → {led3['status']}")

        logs = try_call(lambda: R06.get(f"/api/v1/compliance/access-logs?applyId={st['app_a']}"))
        run.check('J8-访问日志可查',
                  logs['status'] == 200 and len(logs['json']) >= 1,
                  f"R06 access-logs → {logs['status']}, 条数={len(logs['json'])}")

        bad = try_call(lambda: R05.post('/api/v1/compliance/subject-requests', json={
            'applyId': st['app_b'], 'requestType': '删除'}))
        sr = try_call(lambda: R05.post('/api/v1/compliance/subject-requests', json={
            'applyId': st['app_b'], 'requestType': '删除', 'requesterVerified': True}))
        h1 = try_call(lambda: R05.post(f"/api/v1/compliance/subject-requests/{sr['json'].get('id')}/handle",
                                       json={'handleResult': '同意'}))
        h2 = try_call(lambda: R05.post(f"/api/v1/compliance/subject-requests/{sr['json'].get('id')}/handle",
                                       json={'handleResult': 'KEEL穿行验证删除权,执行不可逆匿名化'}))
        db_ = try_call(lambda: R02.get(f"/api/v1/applications/{st['app_b']}"))
        led2 = try_call(lambda: R05.get('/api/v1/compliance/ledgers'))
        brow = next((i for i in led2['json'] if i.get('applyId') == st['app_b']), {})
        run.check('J8-删除权匿名化不可逆',
                  bad['status'] == 400 and sr['status'] == 201 and h1['status'] == 400
                  and h2['json'].get('anonymizedApplyNo') == db_['json'].get('applyNo')
                  and str(db_['json'].get('name', '')).startswith('候选人')
                  and db_['json'].get('idCardMasked') is None and db_['json'].get('phone') == ''
                  and brow.get('status') == '已匿名化',
                  f"未核验 → {bad['status']}; 登记 → {sr['status']}; 理由4字 → {h1['status']}; "
                  f"handle → 匿名化 {h2['json'].get('anonymizedApplyNo')}; 详情 name={db_['json'].get('name')}, "
                  f"phone={db_['json'].get('phone')!r}, idCardMasked={db_['json'].get('idCardMasked')}; "
                  f"台账 status={brow.get('status')}")

        sweep3 = try_call(lambda: R03.post('/api/v1/compliance/retention-sweep'))
        sweep = try_call(lambda: R05.post('/api/v1/compliance/retention-sweep'))
        run.check('J8-留存清理冒烟',
                  sweep3['status'] == 403 and sweep['status'] == 200 and 'swept' in sweep['json'],
                  f"R03 触发清理 → {sweep3['status']}; R05 → {sweep['status']}, swept={sweep['json'].get('swept')}")

    # ---------- J9 越权·脱敏·认证回归 ----------
    def j9(run):
        r04uid = st["uid"]["R04"]
        d2 = try_call(lambda: R02.get(f"/api/v1/interviews/{st['itv_a']}"))
        d5 = try_call(lambda: R05.get(f"/api/v1/interviews/{st['itv_a']}"))
        run.check('J9-定薪仅R05',
                  (d2['json'].get('decision') or {}).get('offerSalary') is None
                  and bool((d5['json'].get('decision') or {}).get('offerSalary')),
                  f"R02 offerSalary={((d2['json'].get('decision') or {}).get('offerSalary'))!r}; "
                  f"R05 offerSalary={(d5['json'].get('decision') or {}).get('offerSalary')!r}")

        d3 = try_call(lambda: R03.get(f"/api/v1/interviews/{st['itv_a']}"))
        d4 = try_call(lambda: R04.get(f"/api/v1/interviews/{st['itv_a']}"))
        run.check('J9-评语受限标记',
                  d3['json'].get('interviewNote') is None and d3['json'].get('noteRestricted') is True
                  and bool(d4['json'].get('interviewNote')),
                  f"R03 note={d3['json'].get('interviewNote')!r}, restricted={d3['json'].get('noteRestricted')}; "
                  f"R04(面试官)note 非空={bool(d4['json'].get('interviewNote'))}")

        li = try_call(lambda: R04.get('/api/v1/interviews'))
        run.check('J9-R04仅本人场次',
                  len(li['json']) >= 1 and all(i.get('interviewerId') == r04uid for i in li['json']),
                  f"R04 列表 {len(li['json'])} 条, interviewerId 全为本人={all(i.get('interviewerId') == r04uid for i in li['json'])}")

        x1 = try_call(lambda: R03.get('/api/v1/compliance/ledgers'))
        x2 = try_call(lambda: R06.post('/api/v1/applications', json={
            'name': 'KEEL越权样本', 'phone': '13899990009', 'positionId': st['pos_main'],
            'channel': '官方网站', 'consentObtained': True, 'retentionConsent': True}))
        run.check('J9-矩阵抽样403',
                  x1['status'] == 403 and x2['status'] == 403,
                  f"R03 台账 → {x1['status']}; R06 应聘登记 → {x2['status']}(R06 无 application:write)")

    api.step("J0'", '冒烟', j0)
    api.step('J1', '岗位模板建档与维护(S01)', j1)
    api.step('J2', '用人需求提报与审核转在招(S02)', j2)
    api.step('J3', '在招岗位维护与状态变更(S02)', j3)
    api.step('J4', '候选人申请与初筛(S03)', j4)
    api.step('J5', '合规授权与敏感查看(S03)', j5)
    api.step('J6', '面试邀约与执行(S04)', j6)
    api.step('J7', '录用决策与offer(S04)', j7)
    api.step('J8', '合规台账与权利请求(S03-006)', j8)
    api.step('J9', '越权与字段级可见性回归', j9)
