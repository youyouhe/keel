"""keel.client — 认证与请求封装（角色矩阵 + 错误码语义）

提炼自起源项目的长期回归实践: 每轮 login()/req() 模式。
错误码三层语义: HTTP status × error.code × error.message。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ApiError(Exception):
    """服务端业务错误(非 2xx), 携带三层语义。"""
    status: int
    code: str | None = None
    message: str | None = None

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.status} {self.code or ''} {self.message or ''}".strip()


@dataclass
class ApiResult:
    """请求结果: status 与 data(2xx 解析后的 JSON, 非 2xx 为 None)。"""
    status: int
    data: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


AuthFn = Callable[["Client"], str]  # 返回 Bearer token


def demo_login(role_field: str = "roleCode", roles_path: str = "/api/v1/auth/demo-login") -> AuthFn:
    """演示登录策略: POST {roles_path} {role_field: <role>} → {token}。
    起源项目模式: Client.role('R02') 即以该角色取 token(可缓存)。"""
    def _auth(client: "Client", role: str) -> str:
        body = json.dumps({role_field: role}).encode()
        req = urllib.request.Request(client.base_url + roles_path, data=body,
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))["token"]
    return _auth  # type: ignore[return-value]


class Client:
    """HTTP 客户端: token 管理 + 请求 + 错误码语义。

    用法:
        c = Client("https://api.example.com", auth=demo_login())
        r = c.as_role("R02").get("/api/v1/accounts", params={"appasid": "as_001"})
        r = c.post("/api/v1/orders", body={"...": 1}, expect=(200, 201))
    """

    def __init__(self, base_url: str, auth: AuthFn | None = None,
                 default_headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self._auth = auth
        self._default_headers = default_headers or {}
        self._tokens: dict[str, str] = {}
        self._current_token: str | None = None

    # ---- 认证 ----
    def as_role(self, role: str) -> "Client":
        """切换角色(取/缓存 token)。"""
        if self._auth is None:
            raise ValueError("未配置 auth 策略")
        if role not in self._tokens:
            self._tokens[role] = self._auth(self, role)  # type: ignore[misc]
        self._current_token = self._tokens[role]
        return self

    def with_token(self, token: str) -> "Client":
        self._current_token = token
        return self

    # ---- 请求 ----
    def request(self, method: str, path: str, body: Any = None,
                params: dict[str, Any] | None = None,
                expect: tuple[int, ...] = (200,)) -> ApiResult:
        if params:
            from urllib.parse import urlencode
            path = f"{path}{'&' if '?' in path else '?'}{urlencode(params)}"
        headers = dict(self._default_headers)
        if self._current_token:
            headers["Authorization"] = f"Bearer {self._current_token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=headers, method=method)
        try:
            raw = urllib.request.urlopen(req).read().decode()
            result = ApiResult(200, json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode()).get("error", {})
            except Exception:
                err = {}
            result = ApiResult(e.code)
            # 语义化异常仅在状态不在 expect 时抛出
            if e.code not in expect:
                raise ApiError(e.code, err.get("code"), err.get("message")) from None
            result.data = err
        if result.status not in expect and result.ok:
            raise ApiError(result.status, "UNEXPECTED_STATUS",
                           f"{method} {path} → {result.status}, expect {expect}")
        return result

    def get(self, path: str, **kw) -> ApiResult:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> ApiResult:
        return self.request("POST", path, body=body, **kw)

    def put(self, path: str, body: Any = None, **kw) -> ApiResult:
        return self.request("PUT", path, body=body, **kw)

    def delete(self, path: str, **kw) -> ApiResult:
        return self.request("DELETE", path, **kw)

    def try_(self, method: str, path: str, **kw) -> ApiError | None:
        """探针: 期望失败。非 2xx → 返回 ApiError(三层语义); 2xx → None(断言方判越权)。"""
        r = self.request(method, path, expect=tuple(range(200, 600)), **kw)
        if r.ok:
            return None
        err = r.data if isinstance(r.data, dict) else {}
        return ApiError(r.status, err.get("code"), err.get("message"))


@dataclass
class RoleMatrix:
    """角色×权限矩阵: 从 contracts/roles.yaml 加载, 供越权探针生成。

    用法:
        m = RoleMatrix.load_yaml(path)
        for probe in m.probes():            # 生成 (role, action, expect_deny) 探针
            err = client.as_role(probe.role).try_("POST", probe.path, body=probe.body)
            check(probe.name, err is not None and err.status == 403, err)
    """
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load_yaml(cls, path: str) -> "RoleMatrix":
        import re
        text = open(path, encoding="utf-8").read()
        roles: dict[str, dict[str, Any]] = {}
        current = None
        for line in text.splitlines():
            m = re.match(r"^(\S+):\s*$", line)
            if m and not line.startswith(" "):
                current = m.group(1)
                roles[current] = {}
            elif current and ":" in line:
                k, v = line.strip().split(":", 1)
                roles[current][k] = v.strip()
        return cls(roles)

    def denies(self, role: str) -> list[str]:
        return [d.strip() for d in str(self.roles.get(role, {}).get("denies", "")).split(",") if d.strip()]
