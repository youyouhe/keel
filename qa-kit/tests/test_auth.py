"""P1.5 验收 A1-A6: envAuth 三类型扩展( credentials / static-token / custom )。"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from keel.auth import AuthError, build_auth, _dig, _resolve_env_placeholders
from keel.client import Client


class _AuthApi(BaseHTTPRequestHandler):
    """模拟 credentials 登录 + 受保护 API。"""
    tokens = {}          # {token: role}
    counter = {"logins": 0, "api_calls": 0}

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/auth/login":
            _AuthApi.counter["logins"] += 1
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            # 模拟: admin/secret123 → R01, viewer/view123 → R04; 错误密码→401
            users = {"admin": ("secret123", "R01"), "viewer": ("view123", "R04")}
            u = users.get(body.get("username"))
            if not u or u[0] != body.get("password"):
                self._send(401, {"error": "bad credentials"})
                return
            token = f"tok-{body['username']}-{_AuthApi.counter['logins']}"
            _AuthApi.tokens[token] = u[1]
            self._send(200, {"token": token, "user": {"roleCode": u[1]}})
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/api/data":
            _AuthApi.counter["api_calls"] += 1
            auth = self.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
            role = _AuthApi.tokens.get(token)
            if not role:
                self._send(401, {"error": "unauthorized"})
            else:
                self._send(200, {"data": "ok", "role": role})
        else:
            self._send(404, {"error": "not found"})


CRED_CFG = {
    "type": "credentials",
    "path": "/auth/login",
    "accounts": {
        "admin": {"username": "admin", "password": "secret123"},
        "viewer": {"username": "viewer", "password": "view123"},
    },
    "tokenField": "token",
    "roleField": "user.roleCode",
    "roles": {"admin": "R01", "viewer": "R04"},
}


class TestDig(unittest.TestCase):
    def test_dig(self):
        self.assertEqual(_dig({"a": {"b": [7]}}, "a.b[0]"), 7)
        self.assertIsNone(_dig({"a": 1}, "a.b"))
        self.assertEqual(_dig({"x": {"y": "z"}}, "x.y"), "z")

    def test_env_placeholder(self):
        import os
        os.environ["KEEL_TEST_PWD"] = "abc"
        self.assertEqual(_resolve_env_placeholders("{env:KEEL_TEST_PWD}"), "abc")
        self.assertEqual(_resolve_env_placeholders("prefix-{env:KEEL_TEST_PWD}"), "prefix-abc")


class TestA1_A3(unittest.TestCase):
    """A1 credentials 登录 / A2 ROLE_MISMATCH / A3 ENV_AUTH_MISSING。"""

    @classmethod
    def setUpClass(cls):
        _AuthApi.tokens.clear()
        _AuthApi.counter.update(logins=0, api_calls=0)
        cls.srv = HTTPServer(("127.0.0.1", 0), _AuthApi)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_A1_credentials_login_and_api(self):
        auth = build_auth(CRED_CFG)
        c = Client(self.base, auth=auth)
        r = c.as_role("admin").get("/api/data")
        self.assertTrue(r.ok)
        self.assertEqual(r.data["role"], "R01")
        r = c.as_role("viewer").get("/api/data")
        self.assertEqual(r.data["role"], "R04")

    def test_A2_role_mismatch(self):
        bad_cfg = dict(CRED_CFG, roles={"admin": "R99"})  # 期望 R99 但实际 R01
        auth = build_auth(bad_cfg)
        c = Client(self.base, auth=auth)
        with self.assertRaises(AuthError) as ctx:
            c.as_role("admin")
        self.assertEqual(ctx.exception.code, "ROLE_MISMATCH")

    def test_A3_env_auth_missing(self):
        c = Client(self.base)                           # 无 auth
        with self.assertRaises(AuthError) as ctx:
            c.as_role("admin")
        self.assertEqual(ctx.exception.code, "ENV_AUTH_MISSING")
        self.assertIn("envAuth", ctx.exception.message)


class TestA4_Custom(unittest.TestCase):
    """A4: custom 型 journeys.py login 钩子。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keel_auth_")
        jy = Path(self.tmp) / "tests"
        jy.mkdir(parents=True)
        (jy / "journeys.py").write_text(
            "def login(api, key):\n"
            "    if key == 'boss': return 'custom-tok-123', 'R00'\n"
            "    raise ValueError(f'unknown {key}')\n",
            encoding="utf-8")

    def test_custom_login(self):
        auth = build_auth({"type": "custom"}, project_root=Path(self.tmp))
        c = Client("http://localhost:1", auth=auth)
        token = auth(c, "boss")
        self.assertEqual(token, "custom-tok-123")

    def test_custom_no_login_fn(self):
        (Path(self.tmp) / "tests" / "journeys.py").write_text("x=1\n", encoding="utf-8")
        auth = build_auth({"type": "custom"}, project_root=Path(self.tmp))
        c = Client("http://localhost:1", auth=auth)
        with self.assertRaises(AuthError) as ctx:
            auth(c, "boss")
        self.assertEqual(ctx.exception.code, "CUSTOM_NO_LOGIN")


class TestA5_TokenExpiry(unittest.TestCase):
    """A5: token 过期 → 自动重登一次。"""

    @classmethod
    def setUpClass(cls):
        _AuthApi.tokens.clear()
        _AuthApi.counter.update(logins=0, api_calls=0)
        cls.srv = HTTPServer(("127.0.0.1", 0), _AuthApi)
        threading.Thread(target=cls.srv_forever if False else cls.srv.serve_forever,
                         daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_auto_relogin_on_401(self):
        auth = build_auth(CRED_CFG)
        c = Client(self.base, auth=auth)
        c.as_role("admin").get("/api/data")              # 首次登录+请求 OK
        self.assertEqual(_AuthApi.counter["logins"], 1)
        # 模拟 token 过期: 服务端清空 tokens 表
        _AuthApi.tokens.clear()
        r = c.get("/api/data")                            # 旧 token → 401 → 自动重登
        self.assertTrue(r.ok)                             # 第二次用新 token 成功
        self.assertEqual(_AuthApi.counter["logins"], 2)   # 重登了一次


class TestA6_StaticToken(unittest.TestCase):
    """A6(简化): static-token 型。"""

    def test_static_token(self):
        cfg = {"type": "static-token", "tokens": {"admin": "pre-made-tok", "viewer": "vt2"}}
        auth = build_auth(cfg)
        self.assertEqual(auth(None, "admin"), "pre-made-tok")
        self.assertEqual(auth(None, "viewer"), "vt2")
        with self.assertRaises(AuthError):
            auth(None, "ghost")


if __name__ == "__main__":
    unittest.main()
