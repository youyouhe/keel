"""Keel CLI 端到端: new → journey run(mock env) → status → report render → issue dry-run → contract verify"""
import io
import json
import contextlib
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from keel.cli import main


class _Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"status": "ok", "check": {"balanced": True, "diff": 0}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


MINI_JOURNEY = '''
from keel import Journey, Step


def build_journey(api):
    j = Journey("T1 穿行")

    def smoke(run):
        r = api.get("/api/v1/health")
        run.check("健康检查 200", r.status == 200, r.status)

    def gouqi(run):
        data = api.get("/api/v1/health").data
        run.check("[勾稽] diff=0", data["check"]["diff"] == 0, data["check"])

    j.register("J0 越权与多租户", [Step("冒烟", smoke), Step("勾稽", gouqi)])
    return j
'''


class TestCliE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _Api)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.root = tempfile.mkdtemp(prefix="keel_e2e_")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _run(self, *argv, expect_code=0):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                code = main(["--root", self.root, *argv])
            except SystemExit as e:
                code = e.code
        self.assertEqual(code, expect_code, f"{argv} → {code}\n{buf.getvalue()}")
        return buf.getvalue()

    def test_01_new(self):
        out = self._run("new", "T1", "--env-dev", self.base, "--issue-repo", "acme/crm")
        self.assertIn("项目已创建", out)
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "T1", "tests", "journeys.py")))

    def test_02_journey_run(self):
        open(os.path.join(self.root, "T1", "tests", "journeys.py"), "w",
             encoding="utf-8").write(MINI_JOURNEY)
        out = self._run("journey", "run", "T1")
        self.assertIn("2/2", out)
        self.assertIn("报告:", out)
        self.assertTrue(list(__import__("pathlib").Path(
            self.root, "T1", "reports").glob("report-*.json")))

    def test_03_status(self):
        out = self._run("status", "T1")
        self.assertIn("上轮: ✅", out)
        self.assertIn("1/1 轮绿", out)

    def test_04_report_render(self):
        html_out = os.path.join(self.root, "T1", "render.html")
        self._run("report", "render", "T1", "-o", html_out)
        self.assertIn("<!DOCTYPE html>", open(html_out, encoding="utf-8").read())

    def test_05_issue_sync_dry(self):
        out = self._run("issue", "sync", "T1", "--repo", "acme/crm", "--dry-run")
        self.assertIn("issue sync 完成", out)

    def test_06_contract_verify(self):
        ctx = os.path.join(self.root, "ctx.json")
        open(ctx, "w", encoding="utf-8").write(json.dumps({"status": 200}))
        out = self._run("contract", "verify", "T1", "--context", ctx, "--scope", "all")
        self.assertIn("契约状态", out)


if __name__ == "__main__":
    unittest.main()
