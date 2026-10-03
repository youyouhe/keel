"""keel.baseline — 基线四步法(环境守恒)

提炼自起源项目每轮纪律: 前置快照 → 测试 → 还原 → 终态校验。
漂移检测思想源自 e2e 回放缓存三态(replayed/handed off/missed):
  基线指纹不一致时告警而非默默跑错。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

ProbeFn = Callable[[], dict[str, Any]]   # 采集一份系统状态(如 关键科目余额/计数)
RestoreFn = Callable[[], Any]            # 还原动作(如 写回原值/反审核)


@dataclass
class Drift:
    key: str
    before: Any
    after: Any

    def __str__(self) -> str:
        return f"漂移[{self.key}]: {self.before} → {self.after}"


class Baseline:
    """多探针基线: take() 采集, compare() 找漂移。

    用法:
        bl = Baseline()
        bl.add("库存", lambda: {"qty": stock_qty()})
        bl.add("试算", lambda: {"diff": tb_diff()})
        before = bl.take()
        ...测试...
        for d in bl.compare(before): print(d)   # 未还原的漂移
    """

    def __init__(self) -> None:
        self._probes: dict[str, ProbeFn] = {}

    def add(self, key: str, probe: ProbeFn) -> None:
        self._probes[key] = probe

    def take(self) -> dict[str, Any]:
        return {k: p() for k, p in self._probes.items()}

    def compare(self, before: dict[str, Any], after: dict[str, Any] | None = None,
                equals: Callable[[Any, Any], bool] | None = None) -> list[Drift]:
        after = after if after is not None else self.take()
        eq = equals or (lambda a, b: a == b)
        return [Drift(k, before.get(k), after.get(k))
                for k in self._probes if not eq(before.get(k), after.get(k))]


@contextmanager
def guarded(baseline: Baseline, restore: RestoreFn | None = None,
            verify: Callable[[list[Drift]], Any] | None = None,
            name: str = "受控测试"):
    """基线四步上下文: 快照 → yield → 还原 → 终态漂移校验。

    用法:
        with guarded(bl, restore=写回原值, verify=漂移须为空) as g:
            ...写操作测试...
        # 退出时自动: 还原 → 重采 → 漂移非空则打印(verify 可自定义为断言)
    """
    before = baseline.take()
    print(f"[基线] {name}: 前置快照 {list(before)}")
    try:
        yield before
    finally:
        if restore:
            restore()
        drifts = baseline.compare(before)
        if drifts:
            print(f"[基线] ⚠ {name} 终态漂移 {len(drifts)} 项:")
            for d in drifts:
                print("   ", d)
        else:
            print(f"[基线] ✅ {name} 终态与基线一致")
        if verify:
            verify(drifts)
