"""keel.mcp_server — MCP 壳(给 manager agent 的原生工具接口)

与 CLI 同一核心(复用 cli.main), 零依赖标准库实现:
  POST /mcp  JSON-RPC 2.0 → tools/list | tools/call
鉴权: Bearer token(--token 或 KEEL_MCP_TOKEN; 未设则开放, 仅建议本机使用)。
启动: python -m keel mcp-server [--port 8902] [--root projects]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cli import main as cli_main

TOOLS = [
    {
        "name": "keel_project_create",
        "description": "创建 Keel 项目空间(环境登记+契约/旅程模板+状态事实源)",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "description": "项目名, 如 crm"},
            "env_dev": {"type": "string", "description": "dev 环境基地址"},
            "issue_repo": {"type": "string", "description": "GitHub issue 仓 owner/repo"},
        }, "required": ["project"]},
    }, {
        "name": "keel_status_get",
        "description": "查询项目状态: 上轮结果/历史绿率/基线指纹(manager 查状态不靠记忆)",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}}, "required": ["project"]},
    }, {
        "name": "keel_journey_run",
        "description": "执行旅程回归(全量或按骨架段), 自动落报告并更新状态; 返回摘要",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"},
            "section": {"type": "string", "description": "骨架段过滤, 如 J3; 缺省全量"},
            "env": {"type": "string", "description": "dev|test, 默认 dev"},
        }, "required": ["project"]},
    }, {
        "name": "keel_contract_verify",
        "description": "契约不变量校验: confirmed 条目编译为勾稽断言并评估",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"},
            "context_path": {"type": "string", "description": "系统快照 JSON 文件路径"},
            "scope": {"type": "string", "description": "confirmed|draft|all, 默认 confirmed"},
        }, "required": ["project", "context_path"]},
    }, {
        "name": "keel_report_render",
        "description": "最新报告渲染为 HTML(manager 转人类可读链接用)",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"},
            "output": {"type": "string", "description": "输出 html 路径, 默认项目 reports/ 下"}},
            "required": ["project"]},
    }, {
        "name": "keel_issue_sync",
        "description": "失败项同步为 GitHub issues(幂等去重, keel:auto 标签); dry_run 仅预览",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"},
            "repo": {"type": "string", "description": "owner/repo, 缺省用项目登记"},
            "dry_run": {"type": "boolean", "description": "只打印不创建, 默认 false"},
        }, "required": ["project"]},
    },
]

_ARGV = {
    "keel_project_create": lambda a: ["new", a["project"], "--env-dev", a.get("env_dev", ""),
                                      "--issue-repo", a.get("issue_repo", "")],
    "keel_status_get": lambda a: ["status", a["project"]],
    "keel_journey_run": lambda a: (["journey", "run", a["project"]] +
                                   (["--section", a["section"]] if a.get("section") else []) +
                                   (["--env", a["env"]] if a.get("env") else [])),
    "keel_contract_verify": lambda a: (["contract", "verify", a["project"],
                                        "--context", a["context_path"]] +
                                       (["--scope", a["scope"]] if a.get("scope") else [])),
    "keel_report_render": lambda a: (["report", "render", a["project"]] +
                                     (["-o", a["output"]] if a.get("output") else [])),
    "keel_issue_sync": lambda a: (["issue", "sync", a["project"]] +
                                  (["--repo", a["repo"]] if a.get("repo") else []) +
                                  (["--dry-run"] if a.get("dry_run") else [])),
}


def call_tool(name: str, args: dict, root: str = "projects") -> dict:
    """执行工具: 复用 CLI 核心, 捕获输出与退出码。"""
    if name not in _ARGV:
        return {"ok": False, "error": f"unknown tool {name}"}
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            cli_main(["--root", root, *_ARGV[name](args)])
    except SystemExit as e:
        code = e.code or 0
    return {"ok": code == 0, "exitCode": code, "output": buf.getvalue().strip()}


class _Handler(BaseHTTPRequestHandler):
    server_version = "keel-mcp/0.5"
    token: str | None = None
    root: str = "projects"

    def log_message(self, *a):
        pass

    def _json(self, code: int, payload: dict, sse: bool = False):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type",
                         "text/event-stream" if sse else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/mcp":
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "仅支持 POST /mcp"}})
            return
        if self.token:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {self.token}":
                self._json(403, {"error": {"code": "FORBIDDEN", "message": "无效 token"}})
                return
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        except Exception:
            self._json(400, {"error": {"code": "PARSE_ERROR", "message": "body 非合法 JSON"}})
            return
        sse = "text/event-stream" in self.headers.get("Accept", "")
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "keel-mcp", "version": "0.5.0"}}}
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
        elif method == "tools/call":
            p = req.get("params", {})
            out = call_tool(p.get("name", ""), p.get("arguments", {}), self.root)
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "isError": not out.get("ok", False)}}
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {}}
        else:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        if sse:
            body = json.dumps(resp, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body) + 6))
            self.end_headers()
            self.wfile.write(b"data: " + body + b"\n\n")
        else:
            self._json(200, resp)


def serve(port: int = 8902, token: str | None = None, root: str = "projects") -> None:
    _Handler.token = token or os.environ.get("KEEL_MCP_TOKEN")
    _Handler.root = root
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"keel-mcp serving on http://127.0.0.1:{port}/mcp (root={root},"
          f" auth={'bearer' if _Handler.token else 'open-local'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("keel mcp-server")
    p.add_argument("--port", type=int, default=8902)
    p.add_argument("--token", default="")
    p.add_argument("--root", default="projects")
    a = p.parse_args(argv)
    serve(a.port, a.token or None, a.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
