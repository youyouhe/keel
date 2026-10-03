"""miaosuanpan 领域旅程(EPF 沉淀精选·只读安全集) — 认证由 envAuth 自动装配。"""
from keel import Journey, Step

A = {"appasid": "as_001"}


def build_journey(api) -> Journey:
    j = Journey("miaosuanpan 穿行")

    def login_smoke(run):
        r = api.as_role("R02").get("/api/v1/account-sets", params={})
        run.check("[J0] demo-login + 账套清单=3", r.ok and len(r.data) == 3, r.status)

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

    def mcp_toolset(run):
        from keel.channels.mcp import McpClient
        tok = api.as_role("R05")._current_token
        names = McpClient("http://192.168.8.181:8801", token=tok).tool_names()
        run.check("[平台] MCP 工具=43", len(names) == 43, f"n={len(names)}")

    j.register("J0 越权与多租户", [
        Step("登录冒烟", login_smoke), Step("租户隔离", tenant_isolation),
        Step("缺省租户拒", default_tenant_denied), Step("只读越权拒", readonly_write_denied)])
    j.register("J7 报表勾稽", [
        Step("试算三层", tb_balance), Step("存货对账", inventory_match),
        Step("资金勾稽", funds_match)])
    j.register("J9 审计穿透", [Step("MCP 工具面", mcp_toolset)])
    return j
