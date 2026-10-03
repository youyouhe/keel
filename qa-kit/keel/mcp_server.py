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
import re
import sys
import threading
import time
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


MAX_BODY = 1 * 1024 * 1024          # 1MB
MAX_CONCURRENCY = 8
_gate = threading.Semaphore(MAX_CONCURRENCY)


def audit(tool: str, args: dict, ok: bool, root: str) -> None:
    """审计日志: logs/mcp-audit.jsonl(工具级取证)。"""
    try:
        log_dir = os.path.join(root, "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        safe = {k: (v if not isinstance(v, str) or len(v) < 200 else v[:200] + "...")
                for k, v in args.items()}
        with open(os.path.join(log_dir, "mcp-audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "tool": tool, "args": safe, "ok": ok},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def _inside(path: str, root: str) -> bool:
    """路径必须解析后落在 root 内(防远程任意读写)。"""
    try:
        rp = os.path.realpath(os.path.abspath(path))
        rr = os.path.realpath(os.path.abspath(root))
        return rp == rr or rp.startswith(rr + os.sep)
    except Exception:
        return False


def call_tool(name: str, args: dict, root: str = "projects") -> dict:
    """执行工具: 复用 CLI 核心, 捕获输出与退出码; 含 MCP 层防线。"""
    if name not in _ARGV:
        return {"ok": False, "error": f"unknown tool {name}"}
    # 防线①: context_path 必须落在 root 内且为 .json
    if "context_path" in args and not (
            str(args["context_path"]).endswith(".json")
            and _inside(os.path.join(root, str(args["context_path"])), root)):
        return {"ok": False, "error": "context_path 仅允许 root 内的 .json 文件"}
    # 防线②: issue 仓只允许项目登记值(忽略调用方传入 repo, 防 gh 凭据越权)
    if name == "keel_issue_sync":
        args = {k: v for k, v in args.items() if k != "repo"}
    buf = io.StringIO()
    code = 0
    with _gate:
        try:
            with contextlib.redirect_stdout(buf):
                cli_main(["--root", root, *_ARGV[name](args)])
        except SystemExit as e:
            code = e.code or 0
    out = {"ok": code == 0, "exitCode": code, "output": buf.getvalue().strip()}
    audit(name, args, out["ok"], root)
    return out


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
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                self._json(413, {"error": {"code": "TOO_LARGE",
                                           "message": f"body 超 {MAX_BODY} 字节上限"}})
                return
            req = json.loads(self.rfile.read(length))
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


def serve(host: str = "127.0.0.1", port: int = 8902, token: str | None = None,
          root: str = "projects") -> None:
    _Handler.token = token or os.environ.get("KEEL_MCP_TOKEN")
    _Handler.root = root
    srv = ThreadingHTTPServer((host, port), _Handler)
    scope = "本机回环" if host in ("127.0.0.1", "localhost") else f"⚠ 局域网 {host}(明文HTTP,务必内网使用)"
    print(f"keel-mcp serving on http://{host}:{port}/mcp (root={root}, {scope},"
          f" auth={'bearer' if _Handler.token else '⚠ open(建议 --token)'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("keel mcp-server")
    p.add_argument("--host", default=os.environ.get("KEEL_HOST", "127.0.0.1"),
                   help="绑定地址; 局域网部署用 0.0.0.0 或具体内网 IP")
    p.add_argument("--port", type=int, default=int(os.environ.get("KEEL_PORT", "8902")))
    p.add_argument("--token", default=os.environ.get("KEEL_MCP_TOKEN", ""))
    p.add_argument("--root", default=os.environ.get("KEEL_ROOT", "projects"))
    a = p.parse_args(argv)
    serve(a.host, a.port, a.token or None, a.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
