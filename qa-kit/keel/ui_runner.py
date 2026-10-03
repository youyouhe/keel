"""keel.ui_runner — UI 冒烟段壳调(P2.1/M1)

Keel 不管理浏览器, 仅执行外部 UI 测试命令并摄入结果。
project.json ui 配置: {cmd, cwd, timeoutSec}
规则 U1-U5: 失败进 issue / 未配跳过 / 超时记失败 / status 含统计 / 信任边界。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .primitives import CheckResult, TestRun


def ui_configured(meta: dict) -> bool:
    ui = meta.get("ui") or {}
    return bool(ui.get("cmd"))


def run_ui_smoke(meta: dict, project_root: Path) -> TestRun:
    """执行 UI 冒烟命令并返回 TestRun。未配置时返回 skipped 标注的空 TestRun。"""
    ui = meta.get("ui") or {}
    run = TestRun("UI 冒烟(壳调)")

    if not ui.get("cmd"):                                     # U2: 未配置→跳过
        run.checks.append(CheckResult("(未配置 ui.cmd, 跳过)", True, "skipped"))
        return run

    cmd = ui["cmd"]
    cwd = ui.get("cwd", ".")
    timeout = ui.get("timeoutSec", 300)
    actual_cwd = str(project_root / cwd) if not os.path.isabs(cwd) else cwd

    if not os.path.isdir(actual_cwd):
        run.check("UI 工作目录存在", False, f"cwd 不存在: {actual_cwd}")
        return run

    start = time.time()
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=actual_cwd, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout)
        elapsed = round(time.time() - start, 1)
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")

        # 尝试解析 Playwright JSON 报告行(最后一条 JSON 行)
        tests = _parse_playwright_json(proc.stdout or "")
        if tests:
            for t in tests:
                run.check(f"[UI] {t['title']}", t["ok"],
                          f"{t.get('duration','?')}ms | {t.get('error','')[:80]}")
            passed = sum(1 for t in tests if t["ok"])
            run.check(f"[UI] 冒烟总览({passed}/{len(tests)})", passed == len(tests),
                      f"exit={proc.returncode} elapsed={elapsed}s")
        else:
            # 退化: 仅退出码
            run.check(f"[UI] 冒烟(退出码={proc.returncode})", proc.returncode == 0,
                      f"elapsed={elapsed}s | {output[-200:]}")

        # 附件: 完整输出落 reports/attachments/
        att_dir = project_root / "reports" / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        att_file = att_dir / f"ui-smoke-{time.strftime('%Y%m%d-%H%M%S')}.log"
        att_file.write_text(output[-10000:], encoding="utf-8")

    except subprocess.TimeoutExpired:                          # U3: 超时→失败
        run.check("[UI] 冒烟", False, f"UI_TIMEOUT: {timeout}s 超时")
    except Exception as e:
        run.check("[UI] 冒烟", False, f"{type(e).__name__}: {e}")

    return run


def _parse_playwright_json(stdout: str) -> list[dict[str, Any]] | None:
    """从 Playwright line reporter 输出解析测试结果(JSON 行)。

    Playwright --reporter=line 不产 JSON; 用 --reporter=json 时最后一条
    stdout 行是 JSON。兼容两种:
    ① json reporter: 最后一行 {"suites":[...],"stats":{...}}
    ② line reporter: 解析 ✓/✘ 行(退化)
    """
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    # ① 尝试 JSON
    for line in reversed(lines):
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if "suites" in data or "stats" in data:
                    return _extract_json_tests(data)
            except json.JSONDecodeError:
                continue
    # ② 尝试行解析(✓/✘/passed/failed)
    tests = []
    for line in lines:
        m_ok = re.match(r"^\s*(?:✓|ok|passed)\s+\d+\s+(.+)", line)
        m_fail = re.match(r"^\s*(?:✘|✗|failed)\s+\d+\s+(.+)", line, re.I)
        if m_ok:
            tests.append({"title": m_ok.group(1).strip(), "ok": True})
        elif m_fail:
            tests.append({"title": m_fail.group(1).strip(), "ok": False,
                          "error": line[:120]})
    return tests if tests else None


def _extract_json_tests(data: dict) -> list[dict[str, Any]]:
    """递归提取 Playwright JSON 报告中的 spec/test 条目。"""
    tests: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "tests" in node:
                for t in node["tests"]:
                    title = " > ".join(filter(None, [
                        t.get("title", ""),
                        node.get("title", "") if node.get("title") else "",
                    ]))
                    ok = t.get("expectedStatus", "passed") == "passed" and \
                         t.get("status", "passed") == "passed"
                    tests.append({"title": title, "ok": ok,
                                  "duration": t.get("duration", 0),
                                  "error": t.get("error", {}).get("message", "") if isinstance(t.get("error"), dict) else ""})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data.get("suites", []))
    return tests
