"""crm 领域旅程插件 — keel journey run 会加载 build_journey。"""
from keel import Journey, Step


def build_journey(api) -> Journey:
    j = Journey("crm 穿行")

    def smoke(run):
        r = api.get("/api/v1/health")          # 换成你的端点
        run.check("冒烟: 健康检查", r.ok, r.status)

    j.register("J0 越权与多租户", [Step("冒烟", smoke)])
    # 按 9 段骨架继续注册: j.register("J2 档案域", [...]) ...
    return j
