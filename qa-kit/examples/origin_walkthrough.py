"""起源项目用法走查（脱敏演示：以通用 ERP 形态演示典型测试手法）。

对任意 B 端系统, 一轮受控测试 = 基线四步 + 角色探针 + 勾稽断言 + 三段式报告。
"""
from keel import Client, Finding, Report, Severity, TestRun, demo_login
from keel import Baseline, guarded

BASE = "http://origin-api.internal"          # 你的被测系统
run = TestRun("J1 主数据守卫")
client = Client(BASE, auth=demo_login())

# ---- 基线四步 ----
bl = Baseline()
bl.add("试算", lambda: client.as_role("R02").get(
    "/api/v1/books/trial-balance", params={"period": "202602"}).data["check"])

def restore():
    """写回原值(受控探针的还原动作)。"""
    client.as_role("R05").put("/api/v1/items/1001", body={"amount": 15200})

with guarded(bl, restore=restore, name="守卫探针"):
    # ---- 守卫探针: 闭期置0 应被拒 ----
    err = client.as_role("R02").try_(
        "PUT", "/api/v1/items/1001", body={"amount": 0})
    run.check("闭期置0 → 400 PERIOD_CLOSED",
              err is not None and err.code == "PERIOD_CLOSED", err)

    # ---- 岗位分离: 越权写应 403 ----
    err = client.as_role("R04").try_(
        "POST", "/api/v1/orders", body={"qty": 1})
    run.check("只读角色越权写 → 403",
              err is not None and err.status == 403, err)

# ---- 勾稽断言 ----
tb = client.as_role("R02").get("/api/v1/books/trial-balance",
                               params={"period": "202602"}).data["check"]
run.diff_zero("试算三层·期初", tb["initialDiff"])
run.diff_zero("试算三层·期末", tb["closingDiff"])

# ---- 报告 ----
report = Report(
    title="起源系统 · 守卫回归", conclusion="守卫与勾稽全绿",
    runs=[run],
    findings=[Finding("O-X-1", Severity.OBS, "审计日志对非法租户返回200空",
                      "GET /audit-logs?tenant=ghost → 200 {items:[]}",
                      "与兄弟端点(403/404)对齐")])
print("\n" + report.render_md())
open("report.html", "w", encoding="utf-8").write(report.render_html())
print(run.summary())
