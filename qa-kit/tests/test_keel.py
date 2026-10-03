"""Keel qa-kit 自测: 纯逻辑 + 本地 loopback mock(无外网依赖)。"""
import json
import os
import tempfile
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
        """P2 后: 4xx 不抛异常, 返回原始响应(status+json 可断言)。"""
        r = self.client.as_role("R02").get("/api/bad")
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json["code"], "SCHEMA_INVALID")

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


class TestInvariants(unittest.TestCase):
    def test_json_contract_and_eval(self):
        import tempfile, os
        from keel import InvariantSet
        contract = [{"id": "INV-1", "rule": "试算平衡", "version": 1, "status": "confirmed",
                     "check": {"left": {"path": "tb.check.initialDiff"}, "op": "==", "right": 0}}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(contract, f); p = f.name
        try:
            s = InvariantSet.load(p)
            ctx = {"tb": {"check": {"initialDiff": 0, "closingDiff": 3}}}
            run = s.verify(ctx)
            self.assertEqual(run.passed, 1)            # 只评 confirmed
            run_all = s.verify(ctx, only="all")
            self.assertEqual(len(run_all.checks), 1)
        finally:
            os.unlink(p)

    def test_dig(self):
        from keel.invariants import dig
        self.assertEqual(dig({"a": [{"b": 7}]}, "a[0].b"), 7)
        self.assertIsNone(dig({"a": 1}, "a.b.c"))


class TestJourneys(unittest.TestCase):
    def test_skeleton_run_and_abort(self):
        from keel.journeys import Journey, Step, SKELETON
        j = Journey("样例")
        def good(run): run.check("通过项", True)
        def boom(run): run.check("炸了", False); raise RuntimeError("段故障")
        def after(run): run.check("不应到达", True)
        j.register(SKELETON[0], [Step("正常", good)])
        j.register(SKELETON[1], [Step("临界", boom), Step("后续", after, critical=False)])
        j.register(SKELETON[2], [Step("被跳过", after)])
        r = j.run()
        self.assertIsNotNone(r.aborted_at)
        self.assertIn("J1", r.aborted_at)
        self.assertFalse(r.ok)
        self.assertTrue(r.summary().startswith("[样例] 中止@"))


class TestReportIo(unittest.TestCase):
    def test_json_roundtrip_and_cli(self):
        from keel import Report, Severity, Finding, TestRun
        run = TestRun("J0"); run.check("越权 403", True, "ev")
        rep = Report("回归", conclusion="绿", runs=[run],
                     findings=[Finding("O-1", Severity.OBS, "t", "e", "s")])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(rep.to_dict(), f); p = f.name
        try:
            rep2 = Report.from_dict(json.load(open(p, encoding="utf-8")))
            self.assertEqual(rep2.stats()["total"], 1)
            self.assertEqual(rep2.findings[0].id, "O-1")
            out = p.replace(".json", ".html")
            from keel.cli import main
            self.assertEqual(main(["render-report", p, "-o", out]), 0)
            self.assertIn("<!DOCTYPE html>", open(out, encoding="utf-8").read())
        finally:
            os.unlink(p)
