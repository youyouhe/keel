"""P1.6 验收 C-1~C-6: keel_project_config 字段白名单与掩码。"""
import json
import tempfile
import unittest
from pathlib import Path

from keel.project_config import ConfigOpError, project_config
from keel.project import KeelProject


class TestProjectConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="keel_cfg_")
        KeelProject.create(cls.root, "cfg", env_dev="http://dev")

    def _call(self, **kw):
        return project_config(self.root, "cfg", **kw)

    def test_C1_legal_envAuth_lands(self):
        """C-2: 合法 credentials(密码走 env) → 200 且落盘生效。"""
        r = self._call(env_auth={
            "type": "credentials", "path": "/api/v1/auth/login",
            "accounts": {"admin": {"username": "13800000001", "password": "{env:CRM_PWD}"}},
            "tokenField": "token", "roleField": "user.roleCode",
        })
        self.assertTrue(r["ok"])
        self.assertIn("envAuth: updated", r["changed"])
        # 落盘验证
        meta = json.loads((Path(self.root) / "cfg" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["envAuth"]["type"], "credentials")

    def test_C2_missing_path_rejected(self):
        """C-3: 缺 path → 400 带原因。"""
        with self.assertRaises(ConfigOpError) as ctx:
            self._call(env_auth={"type": "credentials", "accounts": {"a": {"username": "x", "password": "y"}}})
        self.assertEqual(ctx.exception.code, "ENV_AUTH_INVALID")
        self.assertIn("path", ctx.exception.message)

    def test_C3_unknown_type_rejected(self):
        with self.assertRaises(ConfigOpError) as ctx:
            self._call(env_auth={"type": "magic"})
        self.assertEqual(ctx.exception.code, "ENV_AUTH_INVALID")

    def test_C4_ignored_fields(self):
        """C-4: 改 issueRepo 被忽略(不在白名单)。"""
        r = self._call(env={"dev": "http://new-dev", "prod": "http://should-ignore"})
        self.assertIn("env.dev: updated", r["changed"])
        self.assertTrue(any("prod" in i for i in r["ignored"]))

    def test_C5_remove_envAuth(self):
        """C-5: remove 后 as_role 报 ENV_AUTH_MISSING。"""
        self._call(env_auth={"type": "static-token", "tokens": {"admin": "tok"}})
        r = self._call(remove_env_auth=True)
        self.assertTrue(r["ok"])
        from keel.client import Client
        from keel.auth import AuthError
        c = Client("http://localhost:1")     # 无 auth
        with self.assertRaises(AuthError) as ctx:
            c.as_role("admin")
        self.assertEqual(ctx.exception.code, "ENV_AUTH_MISSING")

    def test_C6_mask_sensitive(self):
        """C-6: 返回值明文密码掩码, {env:VAR} 保留。"""
        r = self._call(env_auth={
            "type": "credentials", "path": "/auth/login",
            "accounts": {
                "admin": {"username": "admin", "password": "{env:SECRET}"},
                "user2": {"username": "bob", "password": "plain123"},
            },
        })
        pw_admin = r["envAuth"]["accounts"]["admin"]["password"]
        pw_user2 = r["envAuth"]["accounts"]["user2"]["password"]
        self.assertEqual(pw_admin, "{env:SECRET}")     # env 占位保留
        self.assertEqual(pw_user2, "***")               # 明文掩码

    def test_C7_env_update(self):
        r = self._call(env={"dev": "http://updated"})
        self.assertIn("env.dev: updated", r["changed"])
        meta = json.loads((Path(self.root) / "cfg" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["env"]["dev"], "http://updated")

    def test_C8_no_changes_rejected(self):
        with self.assertRaises(ConfigOpError) as ctx:
            self._call()
        self.assertEqual(ctx.exception.code, "NO_CHANGES")

    def test_C9_mcp_end_to_end(self):
        """MCP 全链: project_config → 掩码返回。"""
        from keel.mcp_server import call_tool
        r = call_tool("keel_project_config", {
            "project": "cfg",
            "envAuth": {"type": "demo-login", "path": "/auth/demo"},
        }, root=self.root)
        self.assertTrue(r["ok"])
        self.assertIn("envAuth", r)
        self.assertEqual(r["envAuth"]["type"], "demo-login")


if __name__ == "__main__":
    unittest.main()
