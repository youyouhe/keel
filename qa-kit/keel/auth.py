"""keel.auth — 认证策略工厂(P1.5: envAuth 三类型扩展)

类型:
- demo-login  : POST {path} {roleField: key} → {token}
- credentials : POST {path} {username, password} → tokenField; roleField 校验角色
- static-token: 预签发 token 按角色映射
- custom      : journeys.py 顶层 login(api, key) -> (token, roleCode) 钩子

通用语义:
- E1: token 按 (project, key) 缓存; 401 时自动重登重试一次
- E2: 登录响应缺 roleField 且 roles 校验表存在 → ROLE_MISMATCH
- E3: 未配 envAuth 时 as_role 报 ENV_AUTH_MISSING(不静默 fallback 裸客户端)
- E4: credentials 的 password 支持 {env:VAR} 从环境变量取
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .client import Client

AuthFn = Callable[[Client, str], str]


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _resolve_env_placeholders(value: str) -> str:
    """E4: {env:VAR_NAME} → os.environ['VAR_NAME']; 未设则报错。"""
    def _sub(m):
        var = m.group(1)
        v = os.environ.get(var)
        if v is None:
            raise AuthError("ENV_VAR_MISSING", f"环境变量 {var} 未设置(用于密码占位)")
        return v
    return re.sub(r"\{env:(\w+)\}", _sub, value)


def _dig(data: Any, path: str) -> Any:
    """从嵌套 dict/list 按 a.b[0].c 取值。"""
    cur = data
    for part in re.split(r"\.", path):
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


# ---- demo-login (现有, 统一走 factory) ----
def _demo_login_factory(cfg: dict) -> AuthFn:
    path = cfg.get("path", "/api/v1/auth/demo-login")
    role_field = cfg.get("roleField", "roleCode")

    def _auth(client: Client, key: str) -> str:
        body = json.dumps({role_field: key}).encode()
        req = urllib.request.Request(client.base_url + path, data=body,
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))["token"]
    return _auth


# ---- credentials ----
def _credentials_factory(cfg: dict) -> AuthFn:
    path = cfg["path"]
    accounts = cfg["accounts"]            # {key: {username, password}}
    token_field = cfg.get("tokenField", "token")
    role_field = cfg.get("roleField", "")  # 登录响应中角色字段路径
    roles_check = cfg.get("roles", {})     # {key: 期望角色}

    username_field = cfg.get("usernameField", "username")  # 兼容旧方式(仅改发送键名)
    login_body_tpl = cfg.get("loginBody")                   # 推荐: 模板映射(accounts 任意键)

    def _auth(client: Client, key: str) -> str:
        acct = accounts.get(key)
        if not acct:
            raise AuthError("ACCOUNT_NOT_FOUND", f"envAuth.accounts 中无 {key!r}")
        pwd = _resolve_env_placeholders(acct["password"])
        if login_body_tpl:
            # loginBody 模板: {"phone": "{username}", "password": "{password}"}
            # 占位符 {key} 替换为 accounts[key][key] 的值; 模板键名 = 实际发送字段名
            body_dict = {}
            for send_key, tpl_val in login_body_tpl.items():
                if not isinstance(tpl_val, str):
                    body_dict[send_key] = tpl_val
                    continue
                # 替换 {placeholder}
                import re as _re
                def _sub(m):
                    ph = m.group(1)
                    if ph not in acct:
                        raise AuthError("LOGIN_BODY_PLACEHOLDER",
                            f"loginBody 占位符 {{{ph}}} 在 accounts[{key!r}] 中不存在; "
                            f"可用键: {list(acct.keys())}")
                    return _resolve_env_placeholders(str(acct[ph]))
                body_dict[send_key] = _re.sub(r"\{(\w+)\}", _sub, tpl_val)
            body = json.dumps(body_dict).encode()
        else:
            # 默认行为(向后兼容): usernameField 重命名 或 标准 username
            body = json.dumps({username_field: acct["username"], "password": pwd}).encode()
        req = urllib.request.Request(client.base_url + path, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            resp = json.load(urllib.request.urlopen(req))
        except Exception as e:
            detail = ""
            if hasattr(e, "read"):
                try:
                    detail = e.read().decode()[:100]
                except Exception:
                    pass
            raise AuthError("LOGIN_FAILED",
                f"登录请求失败({path}): {type(e).__name__} {getattr(e, 'code', '')} {detail}")
        token = _dig(resp, token_field)
        if not token or not isinstance(token, str):
            raise AuthError("TOKEN_FIELD_MISSING", f"登录响应无 {token_field!r}")
        # E2: 角色校验
        if roles_check:
            actual = _dig(resp, role_field) if role_field else None
            expected = roles_check.get(key)
            if actual != expected:
                raise AuthError("ROLE_MISMATCH",
                                f"key={key} 登录角色 {actual!r} ≠ 期望 {expected!r}")
        return token
    return _auth


# ---- static-token ----
def _static_token_factory(cfg: dict) -> AuthFn:
    tokens = cfg["tokens"]                # {key: token}

    def _auth(client: Client, key: str) -> str:
        t = tokens.get(key)
        if not t:
            raise AuthError("ACCOUNT_NOT_FOUND", f"envAuth.tokens 中无 {key!r}")
        return t
    return _auth


# ---- custom(journeys.py 钩子) ----
def _custom_factory(project_root: Path | None) -> AuthFn:
    def _auth(client: Client, key: str) -> str:
        if project_root is None:
            raise AuthError("CUSTOM_NO_PROJECT", "custom 型需要项目空间路径")
        jy = project_root / "tests" / "journeys.py"
        if not jy.exists():
            raise AuthError("CUSTOM_NO_JOURNEYS", f"journeys.py 不存在: {jy}")
        import importlib.util
        spec = importlib.util.spec_from_file_location("_keel_auth_custom", jy)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "login", None)
        if not callable(fn):
            raise AuthError("CUSTOM_NO_LOGIN",
                            "journeys.py 顶层需定义 def login(api, key) -> (token, roleCode)")
        result = fn(client, key)
        if isinstance(result, tuple) and len(result) == 2:
            token, _ = result
            return token
        if isinstance(result, str):
            return result
        raise AuthError("CUSTOM_BAD_RETURN",
                        "login() 应返回 (token, roleCode) 元组或 token 字符串")
    return _auth


# ---- 工厂 ----
def build_auth(env_auth: dict | None, project_root: Path | None = None) -> AuthFn | None:
    """根据 envAuth 配置构造认证函数; 未配返回 None(裸客户端)。"""
    if not env_auth or not env_auth.get("type"):
        return None
    t = env_auth["type"]
    if t == "demo-login":
        return _demo_login_factory(env_auth)
    if t == "credentials":
        return _credentials_factory(env_auth)
    if t == "static-token":
        return _static_token_factory(env_auth)
    if t == "custom":
        return _custom_factory(project_root)
    raise AuthError("AUTH_TYPE_UNKNOWN", f"未知 envAuth.type: {t!r}; "
                    f"可选: demo-login|credentials|static-token|custom")
