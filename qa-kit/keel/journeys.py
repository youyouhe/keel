"""keel.journeys — 旅程执行器(L4: 泛化 9 段骨架实例化)

骨架段固定(事务型系统同构), 段内步骤由领域插件注册。
journey = 有序段; step = (名称, 可调用) — 可调用抛异常即段失败, 后续段跳过。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .primitives import TestRun

# 泛化 9 段骨架(源自穿行实践归纳, B 端事务系统同构)
SKELETON = [
    "J0 越权与多租户", "J1 主数据建账守卫", "J2 档案域",
    "J3 业务单据循环", "J4 周期关账", "J5 季度/年度汇总",
    "J6 跨期承接", "J7 报表勾稽", "J8 次期初始化", "J9 审计穿透",
]

StepFn = Callable[[TestRun], None]


@dataclass
class Step:
    name: str
    fn: StepFn
    critical: bool = True   # critical 失败 → 中止旅程; 否则继续


@dataclass
class JourneyResult:
    journey: str
    runs: list[TestRun] = field(default_factory=list)
    aborted_at: str | None = None

    @property
    def ok(self) -> bool:
        return self.aborted_at is None and all(not r.failed for r in self.runs)

    def summary(self) -> str:
        p = sum(r.passed for r in self.runs)
        n = sum(len(r.checks) for r in self.runs)
        state = "完成" if self.aborted_at is None else f"中止@{self.aborted_at}"
        return f"[{self.journey}] {state} · {p}/{n} 断言"


class Journey:
    """一段旅程: 领域插件按骨架段注册步骤。

    用法:
        j = Journey("CRM 穿行")
        j.register("J0 越权与多租户", [
            Step("viewer 越权写 403", check_viewer_readonly),
            Step("跨租户读 403", check_tenant_isolation),
        ])
        j.register("J3 业务单据循环", [...])
        result = j.run()
    """

    def __init__(self, name: str):
        self.name = name
        self._sections: list[tuple[str, list[Step]]] = []

    def register(self, section: str, steps: list[Step]) -> None:
        if section not in SKELETON:
            raise ValueError(f"未知骨架段 {section!r}; 合法段: {SKELETON}")
        self._sections.append((section, steps))

    def run(self) -> JourneyResult:
        result = JourneyResult(self.name)
        for section, steps in self._sections:
            run = TestRun(section)
            result.runs.append(run)
            for st in steps:
                if result.aborted_at:
                    break
                try:
                    st.fn(run)
                except Exception as e:  # 段内异常=断言失败
                    run.check(f"{st.name} (异常)", False, f"{type(e).__name__}: {e}")
                    if st.critical:
                        result.aborted_at = f"{section}/{st.name}"
        return result
