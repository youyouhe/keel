"""miaosuanpan 领域旅程 — 认证由 envAuth 自动装配。
J0/J7/J9 只读安全集(沿用,断言改鲁棒);J10-J12 为 2026-10-05 新增写路径旅程:
J10/J11 以 as_001 为靶子(用户拍板;每轮推进其当前期间,可反复跑),J12 每轮自建
独立账套验证 M4b 蒸馏契约。口径备注:费用凭证走应付计提(不动 1001/1002,保资金
账实核对);每个新期间先折旧计提(appasid 走 body;当期已提 409 亦过);
辅助核算科目分录动态挂 auxItemId;审核走 R05/R02 双通道(自审规避两头都不卡)。"""
from keel import Journey, Step

A = {"appasid": "as_001"}
SEEDED = ("as_001", "as_002", "as_003")
TARGET = "as_001"          # J10/J11 写路径靶子(用户拍板 2026-10-05)


def build_journey(api) -> Journey:
    j = Journey("miaosuanpan 穿行")

    # ---------- J0 越权与多租户(只读) ----------
    def login_smoke(run):
        r = api.as_role("R02").get("/api/v1/account-sets", params={})
        rows = r.data if isinstance(r.data, list) else (r.data or {}).get("items", [])
        ids = [x.get("appasid") or x.get("id") for x in rows]
        run.check("[J0] demo-login + 种子账套三件套在", r.ok and all(s in ids for s in SEEDED),
                  {"status": r.status, "n": len(ids)})

    def tenant_isolation(run):
        err = api.as_role("R02").try_("GET", "/api/v1/vouchers", params={"appasid": "as_999"})
        run.check("[J0] as_999 → 403/404", err is not None and err.status in (403, 404), err)

    def default_tenant_denied(run):
        err = api.as_role("R02").try_("GET", "/api/v1/vouchers")
        run.check("[J0] 缺省 appasid → 拒", err is not None and err.status in (400, 403, 404), err)

    def readonly_write_denied(run):
        err = api.as_role("R04").try_("POST", "/api/v1/vouchers", params={"appasid": "as_001"},
                                      body={"period": "202603", "date": "2026-03-05",
                                            "entries": [{"accountCode": "1001", "debit": 1,
                                                         "summary": "keel-probe"},
                                                        {"accountCode": "1002", "credit": 1,
                                                         "summary": "keel-probe"}]})
        run.check("[J0] R04 越权写 → 403", err is not None and err.status == 403, err)

    # ---------- J7 报表勾稽(只读,沿用) ----------
    def tb_balance(run):
        tb = api.as_role("R02").get("/api/v1/books/trial-balance",
                                    params={**A, "period": "202603"}).data
        c = tb.get("check", {})
        run.check("[J7] 试算三层平衡", c.get("initialDiff") == 0 and c.get("closingDiff") == 0,
                  {k: c.get(k) for k in ("initialDiff", "closingDiff", "balanced")})

    def inventory_match(run):
        r = api.as_role("R02").get("/api/v1/inventory/reconciliation", params=A).data
        run.check("[J7] 存货对账 allMatched", r.get("allMatched") is True, "")

    def funds_match(run):
        r = api.as_role("R02").get("/api/v1/funds/reconciliation",
                                   params={**A, "period": "202603"}).data
        rows = r.get("items", [])
        bad = [i.get("name") for i in rows if not i.get("matched")]
        run.check("[J7] 资金勾稽双行 matched", rows and not bad, bad)

    # ---------- J9 MCP 工具面(修鲁棒:数量不缩 + P2 四工具在册) ----------
    def mcp_toolset(run):
        from keel.channels.mcp import McpClient
        tok = api.as_role("R05")._current_token
        names = McpClient("http://192.168.8.181:8801", token=tok).tool_names()
        need = ("workflow_start", "workflow_get", "workflow_advance", "workflow_gate")
        run.check("[平台] MCP 工具面:P2 四工具在册且总数不缩",
                  all(n in names for n in need) and len(names) >= 43, f"n={len(names)}")

    # ---------- 写路径公共件 ----------
    ST = {}
    _w = lambda r: (r.data or {}).get("workflow") or (r.data or {})

    def _rows(r):
        d = r.data
        return d if isinstance(d, list) else (d or {}).get("items", (d or {}).get("vouchers", [])) or []

    def _nextp(p):
        y, m = int(p[:4]), int(p[4:6])
        m += 1
        if m > 12:
            y, m = y + 1, 1
        return f"{y}{m:02d}"

    def _entry(api, asid, code, summary, debit=None, credit=None):
        """构造分录;辅助核算科目自动挂该类别第一个在用档案"""
        e = {"accountCode": code, "summary": summary}
        if debit is not None:
            e["debit"] = debit
        if credit is not None:
            e["credit"] = credit
        accs = _rows(api.as_role("R02").get("/api/v1/accounts", params={"appasid": asid}))
        acc = next((a for a in accs if a.get("code") == code), None) or {}
        if acc.get("isAuxiliary") or acc.get("is_auxiliary"):
            cat = acc.get("auxCategory") or acc.get("aux_category")
            items = _rows(api.as_role("R02").get("/api/v1/aux-items", params={"appasid": asid}))
            it = next((x for x in items if x.get("category") == cat and x.get("isActive") in (1, True, None)), None) \
                or next((x for x in items if x.get("category") == cat), None)
            if it and it.get("id"):
                e["auxItemId"] = it["id"]
        return e

    def _audit_open_vouchers(api, asid, p, run, label):
        """双通道交叉审核:R05 审李主管制的,R02 审陈代账制的(自审规避两头都不卡)"""
        for auditor in ("R05", "R02"):
            lst = api.as_role(auditor).get("/api/v1/vouchers", params={"appasid": asid, "period": p})
            open_ids = [x.get("id") for x in _rows(lst) if not x.get("isAudited") and not x.get("is_audited")]
            if open_ids:
                api.as_role(auditor).post("/api/v1/vouchers/batch-audit", params={"appasid": asid},
                                          body={"ids": open_ids})
        lst = api.as_role("R05").get("/api/v1/vouchers", params={"appasid": asid, "period": p})
        remain = [x.get("id") for x in _rows(lst) if not x.get("isAudited") and not x.get("is_audited")]
        run.check(label + " · 交叉审核完成(R05/R02 双通道,零未审)", len(remain) == 0,
                  {"remain": len(remain)})

    def _prep_period(api, asid, run, label):
        """折旧计提(appasid 走 body,当期已提 409 亦过)→ 收入/费用计提两张(动态挂辅助,不动资金科目)→ 双通道审核"""
        cur = api.as_role("R02").get(f"/api/v1/account-sets/{asid}", params={}).data or {}
        p = cur.get("currentPeriod")
        run.check(label + " · 靶期=当前期间", bool(p), p)
        dp = api.as_role("R05").post("/api/v1/assets/depreciate", params={},
                                     body={"appasid": asid})
        run.check(label + " · 折旧计提(当期已提 409 亦过)",
                  dp.status in (200, 201, 409), {"status": dp.status})
        v1 = api.as_role("R02").post("/api/v1/vouchers", params={"appasid": asid}, body={
            "period": p, "date": f"{p[:4]}-{p[4:6]}-15", "entries": [
                _entry(api, asid, "1122", "keel 赊销一批", debit=1130),
                _entry(api, asid, "5001", "keel 主营业务收入", credit=1130)]})
        v2 = api.as_role("R02").post("/api/v1/vouchers", params={"appasid": asid}, body={
            "period": p, "date": f"{p[:4]}-{p[4:6]}-20", "entries": [
                _entry(api, asid, "5602", "keel 管理费用(应付计提)", debit=400),
                _entry(api, asid, "2202", "keel 应付费用", credit=400)]})
        run.check(label + " · 制单两张 201(收入+费用计提,不动资金科目)",
                  v1.ok and v2.ok, [getattr(v1, "status", None), getattr(v2, "status", None)])
        _audit_open_vouchers(api, asid, p, run, label)
        return p

    def _vcount(api, asid, p):
        lst = api.as_role("R02").get("/api/v1/vouchers", params={"appasid": asid, "period": p})
        return len(_rows(lst))

    # ---------- J10 月结工作流全链(P2 状态机) ----------
    def j10_setup(run):
        ST["j10p"] = _prep_period(api, TARGET, run, "[J10]")

    def j10_flow(run):
        asid, p = TARGET, ST["j10p"]
        s = api.as_role("R05").post("/api/v1/workflows", params={"appasid": asid},
                                    body={"type": "month_close", "period": p})
        w = _w(s)
        run.check("[J10] 发起 month_close:RUNNING + 4 步册",
                  s.status == 201 and w.get("status") == "RUNNING" and len(w.get("steps") or []) == 4,
                  {"status": s.status, "w": w.get("status")})
        wid = w.get("id")
        a = api.as_role("R05").post(f"/api/v1/workflows/{wid}/advance", params={"appasid": asid}, body={})
        wv = _w(a)
        run.check("[J10] advance → L2 结转门挂起(preflight 自动过)",
                  wv.get("status") == "WAITING_HUMAN" and wv.get("currentStep") == "carry_forward",
                  {"w": wv.get("status"), "cur": wv.get("currentStep")})
        g1 = api.as_role("R05").post(f"/api/v1/workflows/{wid}/gate", params={"appasid": asid},
                                     body={"step": "carry_forward", "decision": "approve", "note": "keel 批准结转"})
        w1 = _w(g1)
        st = {x.get("stepKey"): x.get("status") for x in (w1.get("steps") or [])}
        run.check("[J10] 批准结转 → verify 过 → L3 结账门",
                  w1.get("status") == "WAITING_HUMAN" and st.get("carry_forward") == "DONE" and st.get("verify") == "DONE",
                  {"w": w1.get("status"), "steps": st, "http": g1.status})
        g2 = api.as_role("R05").post(f"/api/v1/workflows/{wid}/gate", params={"appasid": asid},
                                     body={"step": "close", "decision": "approve", "note": "keel 批准结账"})
        run.check("[J10] 批准结账 → COMPLETED", _w(g2).get("status") == "COMPLETED",
                  {"status": g2.status, "w": _w(g2).get("status")})
        cur = api.as_role("R02").get(f"/api/v1/account-sets/{asid}", params={}).data or {}
        run.check("[J10] 期间推进 {}→{}".format(p, _nextp(p)), cur.get("currentPeriod") == _nextp(p),
                  cur.get("currentPeriod"))
        chain = api.as_role("R02").get("/api/v1/audit-logs", params={"appasid": asid, "verify": "true"}).data or {}
        run.check("[J10] 审计哈希链 chainValid / unchained=0",
                  chain.get("chainValid") is True and chain.get("unchained") == 0, chain)

    # ---------- J11 驳回与幂等重做(P2-D1) ----------
    def j11_setup(run):
        ST["j11p"] = _prep_period(api, TARGET, run, "[J11]")

    def j11_reject_redo(run):
        asid, p = TARGET, ST["j11p"]
        s = api.as_role("R05").post("/api/v1/workflows", params={"appasid": asid},
                                    body={"type": "month_close", "period": p})
        wid = _w(s).get("id")
        api.as_role("R05").post(f"/api/v1/workflows/{wid}/advance", params={"appasid": asid}, body={})
        g1 = api.as_role("R05").post(f"/api/v1/workflows/{wid}/gate", params={"appasid": asid},
                                     body={"step": "carry_forward", "decision": "approve", "note": "keel 流①批准结转"})
        w1 = _w(g1)
        run.check("[J11] 流①批准结转 → 到结账门",
                  w1.get("status") == "WAITING_HUMAN" and w1.get("currentStep") == "close",
                  {"w": w1.get("status"), "cur": w1.get("currentStep"), "http": g1.status})
        gr = api.as_role("R05").post(f"/api/v1/workflows/{wid}/gate", params={"appasid": asid},
                                     body={"step": "close", "decision": "reject", "note": "keel 驳回结账"})
        wr = _w(gr)
        run.check("[J11] 驳回结账 → CANCELLED(已过账不回滚)",
                  wr.get("status") == "CANCELLED", {"w": wr.get("status"), "http": gr.status})
        cur = api.as_role("R02").get(f"/api/v1/account-sets/{asid}", params={}).data or {}
        run.check("[J11] 驳回后期间未推进(仍 {})".format(p), cur.get("currentPeriod") == p,
                  cur.get("currentPeriod"))
        s2 = api.as_role("R05").post("/api/v1/workflows", params={"appasid": asid},
                                     body={"type": "month_close", "period": p})
        w2 = _w(s2)
        run.check("[J11] 终态放行:同期间重发起 201", s2.status == 201 and w2.get("id") != wid,
                  {"status": s2.status})
        wid2 = w2.get("id")
        a2 = api.as_role("R05").post(f"/api/v1/workflows/{wid2}/advance", params={"appasid": asid}, body={})
        steps2 = {x.get("stepKey"): x for x in (_w(a2).get("steps") or [])}
        gd = (steps2.get("carry_forward") or {}).get("detail") or {}
        run.check("[J11] 门快照标记 alreadyCarriedForward + 指向已有凭证",
                  gd.get("alreadyCarriedForward") is True and len(gd.get("existingVoucherIds") or []) > 0, gd)
        g3 = api.as_role("R05").post(f"/api/v1/workflows/{wid2}/gate", params={"appasid": asid},
                                     body={"step": "carry_forward", "decision": "approve", "note": "keel 流②幂等批准"})
        st3 = {x.get("stepKey"): x for x in (_w(g3).get("steps") or [])}.get("carry_forward", {})
        run.check("[J11] 幂等跳过:步骤 DONE kind=already_carried_forward",
                  st3.get("status") == "DONE" and (st3.get("detail") or {}).get("kind") == "already_carried_forward",
                  st3.get("status"))
        n_before = _vcount(api, asid, p)
        g4 = api.as_role("R05").post(f"/api/v1/workflows/{wid2}/gate", params={"appasid": asid},
                                     body={"step": "close", "decision": "approve", "note": "keel 流②批准结账"})
        run.check("[J11] 批准结账 → COMPLETED(重做之路打通)", _w(g4).get("status") == "COMPLETED",
                  {"w": _w(g4).get("status"), "http": g4.status})
        n_after = _vcount(api, asid, p)
        run.check("[J11] 结转凭证未重复生成", n_before == n_after, {"before": n_before, "after": n_after})
        cur2 = api.as_role("R02").get(f"/api/v1/account-sets/{asid}", params={}).data or {}
        run.check("[J11] 重做完成期间推进 → {}".format(_nextp(p)), cur2.get("currentPeriod") == _nextp(p),
                  cur2.get("currentPeriod"))

    # ---------- J12 蒸馏入库契约(M4b/M4b-D1;新账套内只 R05 有权,全程 R05) ----------
    CPA_A = "注册会计师-keel-甲"
    CPA_B = "注册会计师-keel-乙"

    def _distill_body():
        return {
            "name": "keel 蒸馏销售价税分离", "keywords": ["keel蒸馏销售"], "keyword_mode": "any",
            "fund_direction": "auto",
            "entries": [
                {"summary": "借", "accountCode": "1405", "side": "debit", "amount": "net"},
                {"summary": "借", "accountCode": "2221.01", "side": "debit", "amount": "tax"},
                {"summary": "贷", "accountCode": "2202", "side": "credit", "amount": "gross"}],
            "tax_rule": "auto", "tax_rate": 0.13, "aux_rule": "auto", "priority": 700,
            "sample": {"description": "keel 蒸馏测试商品一批", "amount": 1130},
            "signed_by": CPA_A,
            "source_trace": {"kind": "mining", "candidateId": "keel-journey", "voucherIds": [], "sampleCount": 1},
            "verification_cases": [{"description": "keel 蒸馏测试商品一批", "amount": 1130}]}

    def j12_setup(run):
        import time as _t
        r = api.as_role("R05").post("/api/v1/account-sets", params={}, body={
            "name": f"keel-m4b-{_t.strftime('%H%M%S')}",
            "creditCode": f"91510124KEELM4B{_t.strftime('%H%M%S')}"[:22],
            "currentPeriod": "202607"})
        asid = (r.data or {}).get("appasid") or (r.data or {}).get("id")
        ST["j12"] = asid
        run.check("[J12] · 建账 201", r.ok and bool(asid), {"status": r.status, "asid": asid})

    def j12_distill(run):
        asid = ST["j12"]
        d1 = api.as_role("R05").post("/api/v1/templates/distill", params={"appasid": asid},
                                     body=_distill_body())
        w1 = d1.data or {}
        run.check("[J12] 蒸馏入库 201:v1 CPA甲 + source_trace",
                  d1.status == 201 and w1.get("version") == 1 and w1.get("signedBy") == CPA_A,
                  {"status": d1.status, "v": w1.get("version"), "by": w1.get("signedBy")})
        vid = w1.get("id")
        put = api.as_role("R05").try_("PUT", f"/api/v1/templates/{vid}", params={"appasid": asid},
                                      body={"hint": "偷偷改"})
        run.check("[J12] 蒸馏规则不可原地改(PUT 400)", put is not None and put.status == 400,
                  getattr(put, "status", None))
        miss = api.as_role("R05").try_("POST", "/api/v1/templates/distill", params={"appasid": asid},
                                       body={**_distill_body(), "name": "keel 缺签字", "signed_by": ""})
        run.check("[J12] 缺 CPA 签字 → 400 TEMPLATE_SIGNATURE_REQUIRED",
                  miss is not None and miss.status == 400, getattr(miss, "status", None))
        d2 = api.as_role("R05").post("/api/v1/templates/distill", params={"appasid": asid},
                                     body={**_distill_body(), "name": "keel 蒸馏 v2",
                                           "keywords": ["keel蒸馏销售V2"], "prev_version_id": vid,
                                           "signed_by": CPA_B})
        w2 = d2.data or {}
        run.check("[J12] 升版 = 新版本 v2", d2.status == 201 and w2.get("version") == 2,
                  {"status": d2.status, "v": w2.get("version")})
        v1now = api.as_role("R05").get(f"/api/v1/templates/{vid}", params={"appasid": asid}).data or {}
        run.check("[J12] 升版后 v1 仍是 CPA甲、ARCHIVED(M4b-D1 签字分离)",
                  v1now.get("status") == "ARCHIVED" and v1now.get("signedBy") == CPA_A,
                  {"st": v1now.get("status"), "by": v1now.get("signedBy")})
        rb = api.as_role("R05").post(f"/api/v1/templates/{w2.get('id')}/rollback",
                                     params={"appasid": asid}, body={"reason": "keel 回滚"})
        nv = (rb.data or {}).get("newVersion") or {}
        v3 = api.as_role("R05").get(f"/api/v1/templates/{nv.get('id')}", params={"appasid": asid}).data or {}
        run.check("[J12] 回滚 v3 签字=上一版 CPA甲", v3.get("signedBy") == CPA_A,
                  {"http": rb.status, "by": v3.get("signedBy")})
        lin = api.as_role("R05").get(f"/api/v1/templates/{nv.get('id')}/lineage",
                                     params={"appasid": asid}).data or {}
        nodes = lin.get("nodes") or []
        run.check("[J12] 版本链 3 节点签字 [甲,乙,甲] 无断裂",
                  not lin.get("brokenAt") and [n.get("signedBy") for n in nodes] == [CPA_A, CPA_B, CPA_A],
                  {"n": len(nodes), "brokenAt": lin.get("brokenAt")})
        chain = api.as_role("R05").get("/api/v1/audit-logs", params={"appasid": asid, "verify": "true"}).data or {}
        run.check("[J12] 审计哈希链 chainValid / unchained=0",
                  chain.get("chainValid") is True and chain.get("unchained") == 0, chain)

    j.register("J0 越权与多租户", [
        Step("登录冒烟", login_smoke), Step("租户隔离", tenant_isolation),
        Step("缺省租户拒", default_tenant_denied), Step("只读越权拒", readonly_write_denied)])
    j.register("J7 报表勾稽", [
        Step("试算三层", tb_balance), Step("存货对账", inventory_match),
        Step("资金勾稽", funds_match)])
    j.register("J9 审计穿透", [Step("MCP 工具面", mcp_toolset)])
    j.register("J10 月结工作流全链(P2)", [
        Step("靶期准备(折旧+制单+审核)", j10_setup), Step("状态机全链", j10_flow)])
    j.register("J11 驳回与幂等重做(P2-D1)", [
        Step("靶期准备(折旧+制单+审核)", j11_setup), Step("reject→重做", j11_reject_redo)])
    j.register("J12 蒸馏入库契约(M4b)", [
        Step("建账", j12_setup), Step("契约与版本链", j12_distill)])
    return j
