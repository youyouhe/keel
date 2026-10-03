"""keel.project — 项目空间(manager agent 的状态事实源)

projects/<A>/
├── project.json     # 环境登记(dev/test 地址)、issue 仓、元信息
├── contracts/       # invariants.json / roles / journeys 契约
├── tests/journeys.py  # build_journey(api) -> Journey (领域插件)
├── reports/         # 每轮 report-<ts>.json / .html
└── state.json       # 基线指纹 / 上轮结果 / 契约版本(manager 查状态不靠记忆)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JOURNEY_TEMPLATE = '''"""{name} 领域旅程插件 — keel journey run 会加载 build_journey。

api 是已按 project.json env.auth 配置好认证的 Client:
  - type=demo-login → 直接 api.as_role("R02") 后调用
  - 未配置 auth 的环境 → api 即裸 Client
"""
from keel import Journey, Step

ROLE = "R02"   # 按角色矩阵调整


def build_journey(api) -> Journey:
    j = Journey("{name} 穿行")

    def smoke(run):
        r = api.as_role(ROLE).get("/api/v1/account-sets")   # 换成你的端点
        run.check("冒烟: 登录+清单", r.ok, r.status)

    j.register("J0 越权与多租户", [Step("冒烟", smoke)])
    # 按 9 段骨架继续注册: j.register("J2 档案域", [...]) ...
    return j
'''

INVARIANTS_TEMPLATE = [
    {"id": "INV-EXAMPLE-1", "rule": "示例: 列表接口返回 200",
     "check": {"left": {"path": "status"}, "op": "==", "right": 200},
     "version": 1, "status": "draft"},
]


@dataclass
class KeelProject:
    root: Path

    NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

    @classmethod
    def valid_name(cls, name: str) -> bool:
        return bool(cls.NAME_RE.match(name))

    @classmethod
    def create(cls, root: str | Path, name: str, env_dev: str = "",
               issue_repo: str = "") -> "KeelProject":
        if not cls.valid_name(name):
            raise ValueError(f"非法项目名 {name!r}: 仅允许字母/数字/_/- 且≤64位(防路径遍历)")
        p = Path(root) / name
        if p.exists():
            raise FileExistsError(f"项目已存在: {p}")
        (p / "contracts").mkdir(parents=True)
        (p / "tests").mkdir(parents=True)
        (p / "reports").mkdir(parents=True)
        (p / "project.json").write_text(json.dumps({
            "name": name, "createdAt": time.strftime("%Y-%m-%d %H:%M"),
            "env": {"dev": env_dev, "test": ""},
            "envAuth": {"type": "", "path": "", "roleField": "",
                        "hint": "demo-login 项目: type=demo-login + path + roleField, CLI 将自动装配认证"},
            "issueRepo": issue_repo,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        (p / "contracts" / "invariants.json").write_text(
            json.dumps(INVARIANTS_TEMPLATE, ensure_ascii=False, indent=1), encoding="utf-8")
        (p / "tests" / "journeys.py").write_text(
            JOURNEY_TEMPLATE.format(name=name), encoding="utf-8")
        (p / "state.json").write_text(json.dumps({
            "baseline": None, "lastRun": None, "contractVersion": 0, "runs": [],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return cls(p)

    # ---- 元信息 ----
    @property
    def meta(self) -> dict[str, Any]:
        return json.loads((self.root / "project.json").read_text(encoding="utf-8"))

    @property
    def state(self) -> dict[str, Any]:
        return json.loads((self.root / "state.json").read_text(encoding="utf-8"))

    def save_state(self, st: dict[str, Any]) -> None:
        (self.root / "state.json").write_text(
            json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 旅程执行 ----
    def load_journey(self):
        """动态加载 tests/journeys.py 的 build_journey(api)。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"keel_journey_{self.root.name}", self.root / "tests" / "journeys.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def record_run(self, journey: str, ok: bool, passed: int, total: int,
                   aborted_at: str | None, report_path: str,
                   runs: list | None = None) -> None:
        st = self.state
        st["lastRun"] = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "journey": journey,
            "ok": ok, "passed": passed, "total": total,
            "abortedAt": aborted_at, "report": report_path,
        }
        # API/UI 拆分(有 UI 段时 manager 可一眼区分)
        if runs:
            ui_runs = [r for r in runs if r.name.startswith("UI")]
            if ui_runs:
                api_runs = [r for r in runs if not r.name.startswith("UI")]
                st["lastRun"]["breakdown"] = {
                    "api": f"{sum(r.passed for r in api_runs)}/{sum(len(r.checks) for r in api_runs)}",
                    "ui": f"{sum(r.passed for r in ui_runs)}/{sum(len(r.checks) for r in ui_runs)}",
                }
        st["runs"].append({"time": st["lastRun"]["time"], "ok": ok,
                           "passed": passed, "total": total})
        st["runs"] = st["runs"][-50:]          # 只留最近 50 轮
        self.save_state(st)

    # ---- 报告 ----
    def latest_report_json(self) -> Path | None:
        cands = sorted((self.root / "reports").glob("report-*.json"))
        return cands[-1] if cands else None
