"""P1 验收 C-1/C-2/C-3: loginBody 模板映射。"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from keel.auth import AuthError, build_auth
from keel.client import Client


class _LoginApi(BaseHTTPRequestHandler):
    """模拟 CRM 登录(要求 phone 字段)。"""
    last_body = {}

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        b = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        if self.path == "/auth/login":
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            _LoginApi.last_body = body
            if "phone" in body and body.get("password"):
                self._send(200, {"token": "tok-ok", "user": {"roleCode": "R01"}})
            else:
                self._send(400, {"error": "请输入手机号与密码"})
        else:
            self._send(404, {"error": "not found"})


class TestLoginBody(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _LoginApi)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_C1_loginBody_template(self):
        """C-1: CRM 配 loginBody(phone 键) → 登录成功, 发送体含 phone。"""
        cfg = {
            "type": "credentials", "path": "/auth/login",
            "loginBody": {"phone": "{username}", "password": "{password}"},
            "accounts": {"admin": {"username": "13800000001", "password": "demo123"}},
            "tokenField": "token",
        }
        auth = build_auth(cfg)
        c = Client(self.base, auth=auth)
        token = c.as_role("admin")._current_token
        self.assertEqual(token, "tok-ok")
        self.assertIn("phone", _LoginApi.last_body)      # 发送了 phone 不是 username
        self.assertNotIn("username", _LoginApi.last_body)

    def test_C1b_loginBody_env_placeholder(self):
        """loginBody + {env:VAR} 密码占位。"""
        import os
        os.environ["KEEL_TEST_PW"] = "demo123"
        cfg = {
            "type": "credentials", "path": "/auth/login",
            "loginBody": {"phone": "{username}", "password": "{password}"},
            "accounts": {"admin": {"username": "13800000001", "password": "{env:KEEL_TEST_PW}"}},
            "tokenField": "token",
        }
        auth = build_auth(cfg)
        c = Client(self.base, auth=auth)
        c.as_role("admin")
        self.assertEqual(_LoginApi.last_body["password"], "demo123")

    def test_C2_backward_compat(self):
        """C-2: 未配 loginBody → 行为与 v0.7 一致(username 直发)。"""
        cfg = {
            "type": "credentials", "path": "/auth/login",
            "accounts": {"admin": {"username": "x", "password": "y"}},
            "tokenField": "token",
        }
        auth = build_auth(cfg)
        c = Client(self.base, auth=auth)
        try:
            c.as_role("admin")     # 模拟服务器拒 username(要 phone), 但不 KeyError
        except AuthError as e:
            self.assertEqual(e.code, "LOGIN_FAILED")  # 友好报错, 非 KeyError
        self.assertIn("username", _LoginApi.last_body)  # 发送了 username(向后兼容)

    def test_C3_unknown_placeholder(self):
        """C-3: 模板含未知占位符 → 启动时报错。"""
        cfg = {
            "type": "credentials", "path": "/auth/login",
            "loginBody": {"phone": "{username}", "extra": "{nonexistent}"},
            "accounts": {"admin": {"username": "x", "password": "y"}},
            "tokenField": "token",
        }
        auth = build_auth(cfg)
        c = Client(self.base, auth=auth)
        with self.assertRaises(AuthError) as ctx:
            c.as_role("admin")
        self.assertEqual(ctx.exception.code, "LOGIN_BODY_PLACEHOLDER")


if __name__ == "__main__":
    unittest.main()
