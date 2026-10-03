"""keel-mcp server 自举测试: 用 keel.channels.mcp.McpClient 测自家 MCP。"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from keel.channels.mcp import McpClient
from keel.mcp_server import _Handler, TOOLS, call_tool

MINI_JOURNEY = '''
from keel import Journey, Step


def build_journey(api):
    j = Journey("M1 穿行")

    def smoke(run):
        r = api.get("/api/v1/health")
        run.check("健康检查 200", r.status == 200, r.status)

    j.register("J0 越权与多租户", [Step("冒烟", smoke)])
    return j
'''


class _Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestMcpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_srv = HTTPServer(("127.0.0.1", 0), _Api)
        threading.Thread(target=cls.api_srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.api_srv.server_port}"
        cls.root = tempfile.mkdtemp(prefix="keel_mcp_")
        _Handler.token = None
        _Handler.root = cls.root
        cls.srv = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.client = McpClient(f"http://127.0.0.1:{cls.srv.server_port}", token="x")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.api_srv.shutdown()

    def test_01_tools_list_six(self):
        names = self.client.tool_names()
        for expect in ("keel_project_create", "keel_status_get", "keel_journey_run",
                       "keel_contract_verify", "keel_report_render", "keel_issue_sync"):
            self.assertIn(expect, names)
        self.assertEqual(len(names), 7)  # guide + 六生命周期

    def test_02_create_and_run_over_mcp(self):
        r = self.client.call("keel_project_create",
                             {"project": "M1", "env_dev": self.base,
                              "issue_repo": "acme/m1"})
        self.assertTrue(r["ok"], r)
        # 注入领域旅程
        open(os.path.join(self.root, "M1", "tests", "journeys.py"), "w",
             encoding="utf-8").write(MINI_JOURNEY)
        r = self.client.call("keel_journey_run", {"project": "M1"})
        self.assertTrue(r["ok"], r["output"])
        self.assertIn("1/1", r["output"])
        r = self.client.call("keel_status_get", {"project": "M1"})
        self.assertIn("1/1 轮绿", r["output"])

    def test_03_call_tool_direct_and_bad(self):
        r = call_tool("keel_status_get", {"project": "不存在"}, root=self.root)
        self.assertFalse(r["ok"])
        r = call_tool("nope", {}, root=self.root)
        self.assertIn("unknown tool", r["error"])

    def test_04_issue_sync_dry_over_mcp(self):
        # repo 传入被 MCP 层忽略(防线②), 强制用项目登记值 acme/m1
        r = self.client.call("keel_issue_sync",
                             {"project": "M1", "repo": "attacker/evil", "dry_run": True})
        self.assertTrue(r["ok"])
        self.assertIn("issue sync 完成", r["output"])


if __name__ == "__main__":
    unittest.main()


class TestMcpDefenses(unittest.TestCase):
    """MCP 层防线: 路径遍历/repo 越权/项目名清洗。"""

    def test_project_name_traversal_rejected(self):
        from keel.mcp_server import call_tool
        import tempfile
        root = tempfile.mkdtemp(prefix="keel_def_")
        r = call_tool("keel_project_create", {"project": "../evil"}, root=root)
        self.assertFalse(r["ok"])
        r = call_tool("keel_status_get", {"project": "../../etc"}, root=root)
        self.assertFalse(r["ok"])

    def test_context_path_confined_to_root(self):
        from keel.mcp_server import call_tool
        import tempfile
        root = tempfile.mkdtemp(prefix="keel_def_")
        r = call_tool("keel_contract_verify",
                      {"project": "x", "context_path": "../../secret.json"}, root=root)
        self.assertIn("仅允许 root 内", r["error"])

    def test_issue_sync_repo_ignored_at_mcp_layer(self):
        """MCP 层忽略调用方 repo(强制项目登记值) → CLI 收不到 --repo 即用登记值。"""
        src = open("keel/mcp_server.py", encoding="utf-8").read()
        self.assertIn('args = {k: v for k, v in args.items() if k != "repo"}', src)

    def test_body_limit_constant(self):
        from keel.mcp_server import MAX_BODY
        self.assertEqual(MAX_BODY, 1024 * 1024)


class TestGuide(unittest.TestCase):
    def test_guide_tool_via_mcp(self):
        r = call_tool("keel_guide", {})
        self.assertTrue(r["ok"])
        self.assertIn("五步工作流", r["output"])
        r = call_tool("keel_guide", {"section": "常见坑"})
        self.assertIn("journeys.py 模板", r["output"])

    def test_tools_list_includes_guide_first(self):
        names = [t["name"] for t in TOOLS]
        self.assertEqual(names[0], "keel_guide")
        self.assertIn("先调 keel_guide", [t["description"] for t in TOOLS if t["name"] == "keel_project_create"][0])
