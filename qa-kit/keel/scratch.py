"""keel.scratch — 一次性租户原语(issue #1 方案③: 写路径旅程的环境约定)

用法(journeys.py 内):
    def j12_setup(run):
        asid = api.create_scratch("m4b")      # 建 keel-m4b-<HHMMSS> 账套
        ST["asid"] = asid

    def j12_teardown(run):                    # 注册为 finally 步(非 critical)
        api.cleanup_scratch("m4b")            # 尽力清理(无删除端点时仅登记)

约定:
- 前缀固定 `keel-` 开头(人工可识别, 便于演示环境定期清扫)
- 无删除端点的系统: cleanup 登记到项目空间 scratch-registry.json,
  待被测系统提供删除能力后批量焚毁; 或人工按前缀清扫
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .client import Client

REGISTRY_FILE = "scratch-registry.json"


def _registry_path(project_root: Path | None) -> Path:
    return (project_root or Path(".")) / REGISTRY_FILE


def _load_registry(project_root: Path | None) -> list[dict]:
    p = _registry_path(project_root)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_registry(project_root: Path | None, items: list[dict]) -> None:
    p = _registry_path(project_root)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def create_scratch(client: Client, prefix: str = "",
                   project_root: Path | None = None, **extra: Any) -> str:
    """创建一次性账套(keel-<prefix>-<HHMMSS>), 返回 appasid。

    要求被测系统提供 POST /api/v1/account-sets(妙算盘已验证可用)。
    """
    ts = time.strftime("%H%M%S")
    name = f"keel-{prefix}-{ts}" if prefix else f"keel-{ts}"
    body = {"name": name,
            "creditCode": f"91510124KEEL{ts}{int(time.time()) % 1000:03d}"[:22],
            "currentPeriod": extra.pop("currentPeriod", time.strftime("%Y%m")),
            **extra}
    r = client.post("/api/v1/account-sets", params={}, body=body)
    data = r.data or {}
    asid = data.get("appasid") or data.get("id")
    if not asid:
        raise RuntimeError(f"scratch 账套创建失败: status={r.status} {str(data)[:100]}")
    # 登记(供 cleanup / 人工清扫)
    reg = _load_registry(project_root)
    reg.append({"name": name, "appasid": asid,
                "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "active"})
    _save_registry(project_root, reg)
    return asid


def cleanup_scratch(client: Client, prefix: str = "",
                    project_root: Path | None = None) -> dict:
    """尽力清理: 有 DELETE 端点则焚毁, 无则登记为 pending(待人工/待端点)。

    返回 {deleted: [...], pending: [...]}。
    """
    reg = _load_registry(project_root)
    deleted, pending = [], []
    for item in reg:
        if item.get("status") != "active":
            continue
        if prefix and not str(item.get("name", "")).startswith(f"keel-{prefix}"):
            continue
        asid = item.get("appasid")
        ok = False
        try:
            r = client.delete(f"/api/v1/account-sets/{asid}", params={})
            ok = r.ok
        except Exception:
            ok = False
        if ok:
            item["status"] = "deleted"
            item["deletedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
            deleted.append(asid)
        else:
            item["status"] = "pending"      # 无删除端点: 待被测系统提供能力
            item["pendingAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
            pending.append(asid)
    _save_registry(project_root, reg)
    return {"deleted": deleted, "pending": pending}


def list_scratch(project_root: Path | None = None) -> list[dict]:
    """列出登记的一次性账套(供 status/报告展示)。"""
    return _load_registry(project_root)


# ---- Client 混入: 让 journeys 里直接 api.create_scratch(...) ----
def bind(client_cls) -> None:
    """把 scratch 原语挂到 Client 类(JourneyBuilder 经 __getattr__ 透传)。

    project_root 取自实例属性 _project_root(_env_api 注入)。
    """
    if getattr(client_cls, "_scratch_bound", False):
        return

    def create_scratch_m(self, prefix: str = "", **extra):
        root = extra.pop("project_root", None) or getattr(self, "_project_root", None)
        return create_scratch(self, prefix, root, **extra)

    def cleanup_scratch_m(self, prefix: str = ""):
        return cleanup_scratch(self, prefix, getattr(self, "_project_root", None))

    def list_scratch_m(self):
        return list_scratch(getattr(self, "_project_root", None))

    client_cls.create_scratch = create_scratch_m
    client_cls.cleanup_scratch = cleanup_scratch_m
    client_cls.list_scratch = list_scratch_m
    client_cls._scratch_bound = True
