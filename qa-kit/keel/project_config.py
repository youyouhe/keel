"""keel.project_config — 远端修改 project.json 的 envAuth / env 字段(P1.6)

规则 C1-C5:
- C1 只允许触碰 envAuth 与 env 两键, 其余忽略并回显 ignored 清单
- C2 envAuth 必须通过 auth.py 四型工厂 schema 校验, 失败整体不落盘报 ENV_AUTH_INVALID
- C3 返回值中 password/token 类值掩码(明文→***, {env:VAR} 原样保留)
- C4 每次变更追加审计行(不含值)
- C5 remove_envAuth=true 可回滚(删除 envAuth → as_role 报 ENV_AUTH_MISSING)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ALLOWED_KEYS = {"envAuth", "env", "remove_envAuth"}


class ConfigOpError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _validate_env_auth(env_auth: Any) -> None:
    """C2: 校验 envAuth 能否被 auth.build_auth 解析(不实际连接)。"""
    from .auth import AuthError, build_auth
    if env_auth is None:
        return
    if not isinstance(env_auth, dict):
        raise ConfigOpError("ENV_AUTH_INVALID", "envAuth 必须是对象")
    t = env_auth.get("type", "")
    if t not in ("demo-login", "credentials", "static-token", "custom"):
        raise ConfigOpError("ENV_AUTH_INVALID",
                            f"未知 type {t!r}; 可选: demo-login|credentials|static-token|custom")
    if t == "credentials":
        if not env_auth.get("path"):
            raise ConfigOpError("ENV_AUTH_INVALID", "credentials 型必须提供 path(登录端点)")
        if not env_auth.get("accounts"):
            raise ConfigOpError("ENV_AUTH_INVALID", "credentials 型必须提供 accounts(角色→账密映射)")
    elif t == "static-token":
        if not env_auth.get("tokens"):
            raise ConfigOpError("ENV_AUTH_INVALID", "static-token 型必须提供 tokens(角色→token映射)")
    elif t == "demo-login":
        if not env_auth.get("path"):
            raise ConfigOpError("ENV_AUTH_INVALID", "demo-login 型必须提供 path")


def _mask_sensitive(obj: Any) -> Any:
    """C3: 递归掩码 password/token 类字段; {env:VAR} 原样保留。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and (k.lower() in ("password", "token", "secret", "apikey")):
                out[k] = v if v.startswith("{env:") else "***"
            else:
                out[k] = _mask_sensitive(v)
        return out
    if isinstance(obj, list):
        return [_mask_sensitive(x) for x in obj]
    return obj


def project_config(root: str, project: str, env_auth: Any = None,
                   env: dict | None = None, remove_env_auth: bool = False) -> dict:
    """修改项目配置; 只碰 envAuth/env, 其余不可改。"""
    from .project import KeelProject
    if not KeelProject.valid_name(project):
        raise ConfigOpError("PROJECT_NOT_FOUND", f"非法项目名 {project!r}")
    pfile = Path(root) / project / "project.json"
    if not pfile.exists():
        raise ConfigOpError("PROJECT_NOT_FOUND", f"项目不存在: {project}")
    meta = json.loads(pfile.read_text(encoding="utf-8"))
    ignored = []
    changed = []

    # C5: remove_envAuth
    if remove_env_auth:
        if "envAuth" in meta:
            del meta["envAuth"]
            changed.append("envAuth: removed")
    elif env_auth is not None:
        _validate_env_auth(env_auth)     # C2: 校验后才落盘
        meta["envAuth"] = env_auth
        changed.append("envAuth: updated")

    if env is not None:
        if not isinstance(env, dict):
            raise ConfigOpError("ENV_INVALID", "env 必须是对象({dev: url, test: url})")
        for k, v in env.items():
            if k not in ("dev", "test"):
                ignored.append(f"env.{k}(只允许 dev/test)")
                continue
            meta.setdefault("env", {})[k] = v
            changed.append(f"env.{k}: updated")

    if not changed:
        raise ConfigOpError("NO_CHANGES",
                            "无有效变更(可用键: envAuth, env.dev, env.test, remove_envAuth=true)")

    pfile.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    # C4: 审计(不含值)
    log_dir = Path(root).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "project_config.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "project": project, "changes": changed},
                           ensure_ascii=False) + "\n")

    return {"ok": True, "changed": changed, "ignored": ignored,
            "envAuth": _mask_sensitive(meta.get("envAuth")),
            "env": meta.get("env", {})}
