"""keel.channels.ui — UI 通道(编排 Playwright 项目)

提炼自起源项目双试点结论: UI 基座 = Playwright 原生(@playwright/test)。
本模块不重造浏览器自动化, 只负责把 UI 回归纳入统一编排/统一报告。
认证注入模式: REST 取 token → storageState 复用(见 examples/)。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UiRunResult:
    passed: int
    failed: int
    skipped: int
    duration_ms: float
    raw: str

    @property
    def ok(self) -> bool:
        return self.failed == 0


def run_playwright(project_dir: str | Path, extra_args: list[str] | None = None,
                   reporter: str = "json") -> UiRunResult:
    """在给定 playwright 项目目录执行测试, 解析 JSON 结果。

    项目约定: playwright.config.ts + tests/(认证 setup + 断言)。
    返回 UiRunResult, failed==0 即绿。
    """
    cmd = ["pnpm", "exec", "playwright", "test", f"--reporter={reporter}"]
    if extra_args:
        cmd += extra_args
    proc = subprocess.run(cmd, cwd=str(project_dir), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=1800)
    # JSON reporter 输出在 stdout 末行
    stats = {"passed": 0, "failed": 0, "skipped": 0}
    duration = 0.0
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                j = json.loads(line)
                stats = {k: j.get(k, stats[k]) for k in stats}
                duration = float(j.get("stats", {}).get("duration", 0) or 0) / 1000
                break
            except json.JSONDecodeError:
                continue
    if stats["passed"] == stats["failed"] == stats["skipped"] == 0 and proc.returncode != 0:
        # JSON 解析失败时退化为返回码判断
        stats["failed"] = 1
    return UiRunResult(stats["passed"], stats["failed"], stats["skipped"],
                       duration, proc.stdout[-2000:] + proc.stderr[-2000:])
