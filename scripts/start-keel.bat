@echo off
REM Keel 局域网启动器(Windows) — 配置改这里或用环境变量覆盖
set KEEL_HOST=0.0.0.0
set KEEL_PORT=8902
set KEEL_ROOT=projects
if "%KEEL_MCP_TOKEN%"=="" (
  echo [提示] 未设置 KEEL_MCP_TOKEN, 服务将以无鉴权模式启动(仅建议可信局域网)
)
cd /d %~dp0..\qa-kit
python -m keel mcp-server
