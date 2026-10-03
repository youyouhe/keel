"""keel.channels.mcp — MCP 通道(tools/call 直连)

提炼自起源项目: 被测系统本身是 MCP 服务器时, tools/call 即测试通道。
直连 JSON-RPC(SSE 响应解析), 不依赖任何 MCP 客户端安装。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any


class McpClient:
    """对被测系统 /mcp 端点的直连客户端。

    用法:
        mcp = McpClient("https://api.example.com", token)
        tools = mcp.tools_list()                  # 工具清单(契约漂移检测)
        r = mcp.call("report_issue", {"period": "202602"})
    """

    def __init__(self, base_url: str, token: str, endpoint: str = "/mcp"):
        self.url = base_url.rstrip("/") + endpoint
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._id = 0

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params:
            body["params"] = params
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers=self._headers)
        raw = urllib.request.urlopen(req).read().decode()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # SSE: 取最后一条 data: 行
            lines = [l for l in raw.splitlines() if l.startswith("data:")]
            return json.loads(lines[-1][5:]) if lines else {}

    def tools_list(self) -> list[dict[str, Any]]:
        return self._rpc("tools/list").get("result", {}).get("tools", [])

    def tool_names(self) -> list[str]:
        return sorted(t["name"] for t in self.tools_list())

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        r = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in r:
            raise RuntimeError(f"MCP {name} 调用失败: {r['error']}")
        content = r.get("result", {}).get("content", [])
        text = "".join(c.get("text", "") for c in content)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    def verify_toolset(self, expected: set[str]) -> tuple[bool, dict[str, list[str]]]:
        """契约漂移检测: 工具清单 vs 期望集合。"""
        actual = set(self.tool_names())
        return not (expected - actual) and not (actual - expected), {
            "missing": sorted(expected - actual), "extra": sorted(actual - expected)}
