"""Issue#1 方案③验收: 一次性租户原语(create_scratch/cleanup_scratch/list)。"""
import json
import tempfile
import unittest
from pathlib import Path

from keel.auth import build_auth
from keel.client import Client
from keel.scratch import create_scratch, cleanup_scratch, list_scratch, bind
from keel.client import Client as _C

BASE = "http://192.168.8.181:8801"


def _client():
    auth = build_auth({"type": "demo-login",
                       "path": "/api/v1/auth/demo-login", "roleField": "roleCode"})
    c = Client(BASE, auth=auth)
    c._project_root = None
    return c


class TestScratch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bind(_C)                      # 幂等
        cls.tmp = tempfile.mkdtemp(prefix="keel_scratch_")
        cls.c = _client().as_role("R05")   # 建账套需 R05(管理员)
        cls.c._project_root = Path(cls.tmp)  # scratch 注册表位置

    def test_S1_create_returns_asid_and_registers(self):
        asid = self.c.create_scratch("t1", project_root=Path(self.tmp))
        self.assertTrue(str(asid).startswith("as_"))
        reg = list_scratch(Path(self.tmp))
        self.assertTrue(any(i["appasid"] == asid and i["name"].startswith("keel-t1-")
                            for i in reg))

    def test_S2_cleanup_no_delete_endpoint_goes_pending(self):
        asid = self.c.create_scratch("t2", project_root=Path(self.tmp))
        r = self.c.cleanup_scratch("t2")
        # 妙算盘无 DELETE /account-sets → pending(待被测系统提供能力)
        self.assertIn(asid, r["pending"])

    def test_S3_prefix_scoped_cleanup(self):
        a1 = self.c.create_scratch("pa", project_root=Path(self.tmp))
        a2 = self.c.create_scratch("pb", project_root=Path(self.tmp))
        r = self.c.cleanup_scratch("pa")
        self.assertIn(a1, r["pending"])
        self.assertNotIn(a2, r.get("deleted", []) + r.get("pending", []))

    def test_S4_registry_persists(self):
        n_before = len(list_scratch(Path(self.tmp)))
        self.c.create_scratch("t4", project_root=Path(self.tmp))
        self.assertEqual(len(list_scratch(Path(self.tmp))), n_before + 1)

    def test_S5_builder_passthrough(self):
        """JourneyBuilder.__getattr__ 透传 create_scratch。"""
        from keel.journeys import JourneyBuilder
        b = JourneyBuilder(self.c, "透传测试")
        asid = b.create_scratch("t5", project_root=Path(self.tmp))
        self.assertTrue(str(asid).startswith("as_"))


if __name__ == "__main__":
    unittest.main()
