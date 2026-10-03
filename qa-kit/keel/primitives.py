"""keel.primitives — 断言与勾稽原语

提炼自起源项目 P() 函数与四路勾稽方法论:
  勾稽 = 对账 = 守恒检查, 是事务型系统测试的通用原语。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CheckResult:
    name: str
    ok: bool
    evidence: Any = ""

    def __str__(self) -> str:
        flag = "PASS" if self.ok else "FAIL"
        ev = str(self.evidence)[:160]
        return f"{flag} {self.name}" + (f" | {ev}" if ev else "")


class TestRun:
    """断言收集器: 一轮测试的全部 check + 汇总。

    用法:
        run = TestRun("J3 业务穿行")
        run.check("FIFO 成本=预期", got == exp, {"got": got, "exp": exp})
        ...
        print(run.summary())
    """

    def __init__(self, name: str = ""):
        self.name = name
        self.checks: list[CheckResult] = []

    def check(self, name: str, ok: bool, evidence: Any = "") -> bool:
        r = CheckResult(name, bool(ok), evidence)
        self.checks.append(r)
        print(r)
        return r.ok

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        return f"[{self.name}] {self.passed}/{len(self.checks)} passed" + (
            f" · FAIL: {[c.name for c in self.failed]}" if self.failed else "")

    # ---- 勾稽原语(返回 bool, 自动入 checks) ----
    def diff_zero(self, name: str, diff: float, tolerance: float = 0.01) -> bool:
        """守恒: 差额为零(如 试算 diff、对账 difference)。"""
        return self.check(f"[勾稽] {name} diff=0", abs(diff) <= tolerance, f"diff={diff}")

    def conserved(self, name: str, left: float, right: float, tolerance: float = 0.01) -> bool:
        """守恒: A == B(如 投入=产出+损耗、日记账=科目)。"""
        return self.check(f"[勾稽] {name}: {left} == {right}",
                          abs(left - right) <= tolerance, f"Δ={round(left - right, 4)}")

    def delta_is(self, name: str, before: float, after: float, expected: float,
                 tolerance: float = 0.01) -> bool:
        """双向Δ: 操作前后变动恰为预期(如 出库后库存 -2、红冲后余额回落)。"""
        return self.check(f"[Δ] {name}: {before}→{after} 期望Δ{expected}",
                          abs((after - before) - expected) <= tolerance,
                          f"实际Δ={round(after - before, 4)}")

    def all_matched(self, name: str, rows: list[dict[str, Any]],
                    key: str = "matched") -> bool:
        """allMatched: 对账表全绿(如 存货对账/资金勾稽多行)。"""
        bad = [r for r in rows if not r.get(key)]
        return self.check(f"[勾稽] {name} allMatched({key})", not bad,
                          f"{len(rows) - len(bad)}/{len(rows)}" if rows else "空表")


@dataclass
class Saga:
    """缺陷 saga 追踪: 同一主题跨轮次的攻防时间线。

    用法:
        s = Saga("期初守卫族")
        s.round("R14", "发现单边写 → 修复")
        s.round("R24c", "置0旁路再发现")
        s.close("EPF", "第三代语义定型, 五条断言全绿")
    """
    topic: str
    rounds: list[tuple[str, str]] = field(default_factory=list)
    closed_at: tuple[str, str] | None = None

    def round(self, label: str, note: str) -> None:
        self.rounds.append((label, note))

    def close(self, label: str, note: str) -> None:
        self.closed_at = (label, note)

    def render(self) -> str:
        lines = [f"### Saga: {self.topic}"]
        lines += [f"- **{lb}** {nt}" for lb, nt in self.rounds]
        if self.closed_at:
            lines.append(f"- ✅ **闭环 @ {self.closed_at[0]}**: {self.closed_at[1]}")
        return "\n".join(lines)
