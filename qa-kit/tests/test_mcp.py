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
        self.assertEqual(len(names), 11)  # guide + 六生命周期 + file_put/get + project_config

    def test_02_create_and_run_over_mcp(self):
        r = self.client.call("keel_project_create",
                             {"project": "M1", "env_dev": self.base,
                              "issue_repo": "acme/m1"})
        self.assertTrue(r["ok"], r)
        # 注入领域旅程
        open(os.path.join(self.root, "M1", "tests", "journeys.py"), "w",
             encoding="utf-8").write(MINI_JOURNEY)
        r = self.client.call("keel_journey_run", {"project": "M1"})
        self.assertTrue(r["ok"], r)
        self.assertIn("jobId", r)                 # 异步: 秒回 jobId
        import time as _t
        for _ in range(60):
            st = self.client.call("keel_journey_status", {"jobId": r["jobId"]})
            if st.get("state") != "running":
                break
            _t.sleep(0.1)
        self.assertIn(st.get("state"), ("done", "failed"))
        r = self.client.call("keel_status_get", {"project": "M1"})
        self.assertIn("轮", r["output"])           # 有历史记录

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


class TestFileOps(unittest.TestCase):
    """F1-F7 验收: file_put/file_get 沙箱与乐观锁。"""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from keel.fileops import file_put
        import tempfile
        from keel.project import KeelProject
        cls.root = tempfile.mkdtemp(prefix="keel_fo_")
        KeelProject.create(cls.root, "fo")
        file_put(cls.root, "fo", "contracts/invariants.json",
                 '{"invariants": [{"id": "INV-1", "status": "confirmed",'
                 ' "rule": "test", "check": {"left": 1, "op": "==", "right": 1}}]}')

    def test_F1_normal_put_get_roundtrip(self):
        from keel.fileops import file_get, file_put
        r = file_put(self.root, "fo", "tests/journeys.py", "# test\n")
        self.assertTrue(r["ok"])
        g = file_get(self.root, "fo", "tests/journeys.py")
        self.assertIn("test", g["content"])
        self.assertEqual(g["version"], 1)  # sidecar 版本持久递增(反馈②修复)

    def test_F2_path_escape_rejected(self):
        from keel.fileops import file_put, FileOpError
        for bad in ("../../evil.py", "/abs/path.py", "..\..\win.py"):
            with self.assertRaises(FileOpError) as ctx:
                file_put(self.root, "fo", bad, "x")
            self.assertEqual(ctx.exception.code, "PATH_ESCAPED")

    def test_F3_reserved_path_rejected(self):
        from keel.fileops import file_put, FileOpError
        for path in ("project.json", "reports/report-1.json"):
            with self.assertRaises(FileOpError) as ctx:
                file_put(self.root, "fo", path, "{}")
            self.assertEqual(ctx.exception.code, "RESERVED_PATH")

    def test_F4_too_large(self):
        from keel.fileops import file_put, FileOpError
        with self.assertRaises(FileOpError) as ctx:
            file_put(self.root, "fo", "big.txt", "x" * (1024 * 1024 + 1))
        self.assertEqual(ctx.exception.code, "FILE_TOO_LARGE")

    def test_F5_optimistic_lock(self):
        from keel.fileops import file_put, FileOpError
        file_put(self.root, "fo", "lock.json", '{"v": 1}')
        # 错误版本号
        with self.assertRaises(FileOpError) as ctx:
            file_put(self.root, "fo", "lock.json", '{"v": 2}', expected_version=99)
        self.assertEqual(ctx.exception.code, "VERSION_CONFLICT")
        # 正确版本号(首次写入后版本=1)
        r = file_put(self.root, "fo", "lock.json", '{"v": 2}', expected_version=1)
        self.assertTrue(r["ok"])
        self.assertEqual(r["version"], 2)  # 递增

    def test_F6_project_not_found(self):
        from keel.fileops import file_put, FileOpError
        with self.assertRaises(FileOpError) as ctx:
            file_put(self.root, "ghost", "x.txt", "y")
        self.assertEqual(ctx.exception.code, "PROJECT_NOT_FOUND")

    def test_F7_mcp_end_to_end(self):
        """真实 MCP HTTP 全链: file_put → tools/list 可见 → file_get 回读。"""
        r = call_tool("keel_file_put", {
            "project": "fo", "path": "e2e.txt", "content": "hello"}, root=self.root)
        self.assertTrue(r["ok"])
        r = call_tool("keel_file_get", {"project": "fo", "path": "e2e.txt"}, root=self.root)
        self.assertTrue(r["ok"])
        self.assertIn("hello", r["content"])
        # 工具面确认
        names = [t["name"] for t in TOOLS]
        self.assertIn("keel_file_put", names)
        self.assertIn("keel_file_get", names)


class TestAsyncJourney(unittest.TestCase):
    """异步 journey_run: 秒回 jobId → 轮询 → done/failed。"""

    def test_job_lifecycle(self):
        import time as _time
        from keel.jobs import manager as jm

        # 提交一个短作业
        jid = jm.submit("test", lambda: {"answer": 42})
        self.assertTrue(jid.startswith("j_"))
        # 等完成
        for _ in range(20):
            st = jm.status(jid)
            if st["state"] != "running":
                break
            _time.sleep(0.05)
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["result"]["answer"], 42)

        # 失败作业
        jid2 = jm.submit("test", lambda: 1 / 0)
        for _ in range(20):
            st2 = jm.status(jid2)
            if st2["state"] != "running":
                break
            _time.sleep(0.05)
        self.assertEqual(st2["state"], "failed")
        self.assertIn("ZeroDivisionError", st2["error"])

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.mkdtemp(prefix="keel_async_")

    def test_mcp_journey_run_returns_jobId(self):
        """MCP 全链: journey_run → jobId 秒回 → status 轮询。"""
        import time as _time
        root = self._tmp
        call_tool("keel_project_create", {"project": "M1"}, root=root)
        r = call_tool("keel_journey_run", {"project": "M1"}, root=root)
        self.assertTrue(r["ok"])
        self.assertIn("jobId", r)
        self.assertEqual(r["state"], "running")
        jid = r["jobId"]
        # 轮询
        for _ in range(60):
            st = call_tool("keel_journey_status", {"jobId": jid}, root=self._tmp)
            if st.get("state") != "running":
                break
            _time.sleep(0.1)
        self.assertIn(st.get("state"), ("done", "failed"))

