"""Keel qa-kit 自测: 纯逻辑 + 本地 loopback mock(无外网依赖)。"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from keel import (ApiError, Baseline, Client, Finding, Report, Saga,
                  Severity, TestRun, build_mini_spec, demo_login, guarded)


class _Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def _send(self, code, payload=None, err=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = {"error": err} if err else (payload or {})
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        if self.path == "/auth":
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(200, {"token": f"tok-{body.get('roleCode')}"})
        else:
            self._send(404, err={"code": "NOT_FOUND", "message": "接口不存在"})

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer tok-"):
            self._send(403, err={"code": "FORBIDDEN", "message": "无权访问"}); return
        if self.path.startswith("/api/items"):
            self._send(200, [{"id": 1, "name": "a"}])
        elif self.path.startswith("/api/bad"):
            self._send(400, err={"code": "SCHEMA_INVALID", "message": "参数错误"})
        else:
            self._send(404, err={"code": "NOT_FOUND", "message": "接口不存在"})


class TestPrimitives(unittest.TestCase):
    def test_run_and_gouqi(self):
        r = TestRun("样例")
        self.assertTrue(r.check("常真", True, "evidence"))
        self.assertFalse(r.check("常假", False))
        self.assertTrue(r.diff_zero("试算", 0.005))
        self.assertTrue(r.diff_zero("容差内", 0.009, tolerance=0.01))
        self.assertTrue(r.conserved("投入=产出", 100.0, 100.0))
        self.assertTrue(r.delta_is("库存Δ", 5, 3, -2))
        self.assertTrue(r.all_matched("对账", [{"matched": True}, {"matched": True}]))
        self.assertIn("6/7", r.summary())

    def test_saga(self):
        s = Saga("守卫族"); s.round("R1", "发现"); s.close("EPF", "定型")
        self.assertIn("闭环", s.render())


class TestBaseline(unittest.TestCase):
    def test_drift_and_guarded(self):
        state = {"qty": 10}
        bl = Baseline(); bl.add("qty", lambda: {"qty": state["qty"]})
        before = bl.take()
        state["qty"] = 8
        self.assertEqual(len(bl.compare(before)), 1)          # 漂移检出
        state.update(qty=10)  # 回到基线再进受控段
        seen = {}
        with guarded(bl, restore=lambda: state.update(qty=10),
                     verify=lambda d: seen.update(drifts=d), name="受控"):
            state["qty"] = 6
        self.assertEqual(state["qty"], 10)                      # 已还原
        self.assertEqual(seen["drifts"], [])                    # 终态与基线一致


class TestClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _Mock)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.client = Client(cls.base, auth=demo_login(role_field="roleCode", roles_path="/auth"))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_role_token_cache_and_ok(self):
        r = self.client.as_role("R02").get("/api/items")
        self.assertTrue(r.ok); self.assertEqual(r.data[0]["id"], 1)

    def test_error_semantics(self):
        with self.assertRaises(ApiError) as ctx:
            self.client.as_role("R02").get("/api/bad")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (400, "SCHEMA_INVALID"))

    def test_probe_expect_fail(self):
        c = Client(self.base).with_token("wrong")
        err = c.try_("GET", "/api/items")
        self.assertEqual((err.status, err.code), (403, "FORBIDDEN"))


class TestReport(unittest.TestCase):
    def test_md_and_html(self):
        run = TestRun("J1"); run.check("守卫", True)
        f = Finding("F-X-1", Severity.P2, "标题", "证据", "建议")
        rep = Report("样例报告", conclusion="通过", runs=[run], findings=[f])
        self.assertIn("发现", rep.render_md())
        self.assertIn("F-X-1", rep.render_md())
        h = rep.render_html()
        self.assertIn("<!DOCTYPE html>", h) and self.assertIn("F-X-1", h)


class TestSchemathesis(unittest.TestCase):
    def test_mini_spec_build(self):
        spec = build_mini_spec("http://x", "T", {"/api/a": [("appasid", "{ type: string }")]})
        self.assertIn("openapi: 3.0.3", spec) and self.assertIn("appasid", spec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
