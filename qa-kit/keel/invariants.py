"""keel.invariants — 契约不变量: 加载 + 编译为勾稽断言(L1→L3 落地)

契约格式双轨: .yaml(人写, 需 pyyaml) / .json(机器, 零依赖)。
check 结构化形式(v0.2): {left, op, right} — left/right 为
  字面量 或 {path: "a.b[0].c"} 从被测系统响应取值; op ∈ 比较集。
status: confirmed(实测过) / draft(AI 初稿) / unsourced(待拍板)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .primitives import TestRun

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "abs<=": lambda a, b: abs(a - b) <= b if isinstance(a, (int, float)) else False,
}


def dig(obj: Any, path: str) -> Any:
    """按 a.b[0].c 取值; 取不到返回 None。"""
    cur = obj
    for part in path.split("."):
        m = re.match(r"^([^\[\]]*)((?:\[\d+\])*)$", part)
        if not m:
            return None
        if m.group(1):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(m.group(1))
        for idx in re.findall(r"\[(\d+)\]", part):
            if not isinstance(cur, list):
                return None
            try:
                cur = cur[int(idx)]
            except IndexError:
                return None
    return cur


def _resolve(operand: Any, context: dict[str, Any]) -> Any:
    """操作数: {path:...} → 从上下文取值; 其余字面量。"""
    if isinstance(operand, dict) and "path" in operand:
        return dig(context, operand["path"])
    return operand


@dataclass
class Invariant:
    id: str
    rule: str
    check: dict[str, Any]          # {left, op, right}
    version: int = 1
    status: str = "draft"          # confirmed / draft / unsourced
    evidence: str = ""

    def evaluate(self, context: dict[str, Any]) -> tuple[bool, str]:
        left = _resolve(self.check.get("left"), context)
        right = _resolve(self.check.get("right"), context)
        op = self.check.get("op", "==")
        fn = OPS.get(op)
        if fn is None:
            return False, f"未知算子 {op}"
        if left is None or right is None:
            return False, f"取值失败 left={left!r} right={right!r}"
        return bool(fn(left, right)), f"{left!r} {op} {right!r}"


@dataclass
class InvariantSet:
    """契约不变量集合: 加载/评估/编译为 TestRun 断言。"""
    invariants: list[Invariant] = field(default_factory=list)

    # ---- 加载 ----
    @classmethod
    def load(cls, path: str | Path) -> "InvariantSet":
        p = Path(path)
        if p.suffix in (".yaml", ".yml"):
            try:
                import yaml  # 可选依赖
            except ImportError as e:
                raise RuntimeError("yaml 契约需 pip install pyyaml; 或使用 .json 契约") from e
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        else:
            data = json.loads(p.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("invariants", [])
        return cls([Invariant(
            id=i["id"], rule=i.get("rule", ""), check=i["check"],
            version=int(i.get("version", 1)), status=i.get("status", "draft"),
            evidence=i.get("evidence", "")) for i in items])

    # ---- 使用 ----
    def by_status(self, status: str) -> list[Invariant]:
        return [i for i in self.invariants if i.status == status]

    def verify(self, context: dict[str, Any], run: TestRun | None = None,
               only: str = "confirmed") -> TestRun:
        """对上下文(被测系统快照)评估不变量, 编译为勾稽断言。

        only: 只评该 status(默认 confirmed=已签收的); "all" 全评。
        """
        run = run or TestRun("invariants 契约校验")
        targets = self.invariants if only == "all" else self.by_status(only)
        for inv in targets:
            ok, detail = inv.evaluate(context)
            run.check(f"[{inv.id}] {inv.rule}", ok,
                      f"{detail} · v{inv.version} {inv.status}")
        return run

    def stats(self) -> dict[str, int]:
        s: dict[str, int] = {}
        for i in self.invariants:
            s[i.status] = s.get(i.status, 0) + 1
        return s
