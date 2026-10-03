#!/usr/bin/env sh
# Keel 局域网启动器(Unix/macOS/GitBash)
: "${KEEL_HOST:=0.0.0.0}"      # 局域网监听; 仅本机改 127.0.0.1
: "${KEEL_PORT:=8902}"
: "${KEEL_ROOT:=projects}"
[ -z "$KEEL_MCP_TOKEN" ] && echo "[提示] 未设置 KEEL_MCP_TOKEN, 无鉴权模式(仅建议可信局域网)"
cd "$(dirname "$0")/../qa-kit" && exec python -m keel mcp-server
