# qa-kit — Keel 测试套件（Python）

从起源项目 8 天 31 批次实测资产提炼的可复用库，**新系统第一天即可 import**。零强制依赖（标准库实现）；fuzz 可选装 `pip install .[fuzz]`。

## 安装与自测

```bash
cd qa-kit
pip install -e .           # 或直接把 keel/ 拷进你的项目
python -m unittest discover -s tests   # 8 项自测(loopback mock, 无外网)
```

## 五分钟上手

```python
from keel import Client, TestRun, demo_login

run  = TestRun("冒烟")
api  = Client("https://api.your-biz.com", auth=demo_login())

# 角色 + 错误码语义断言
r = api.as_role("manager").get("/api/v1/customers", params={"tenant": "t1"})
run.check("客户列表可达", r.ok, r.status)

# 越权探针: 期望被拒
err = api.as_role("viewer").try_("POST", "/api/v1/customers", body={"name": "x"})
run.check("viewer 只读越权 403", err is not None and err.status == 403, err)

# 勾稽守恒
run.diff_zero("对账差额", recon["difference"])
run.conserved("投入=产出+损耗", inp, ok + ng + loss)

print(run.summary())
```

## 模块地图（对应 Keel 五层）

| 模块 | 层 | 内容 |
|---|---|---|
| `keel.client` | L2 REST | 角色矩阵 token 缓存、ApiError 三层语义(status×code×message)、`try_` 越权探针、RoleMatrix(roles.yaml 加载) |
| `keel.channels.mcp` | L2 MCP | 被测系统即 MCP 服务器时：tools_list/call 直连(JSON-RPC+SSE)、`verify_toolset` 工具契约漂移检测 |
| `keel.channels.ui` | L2 UI | 编排 Playwright 项目(`run_playwright`)，认证用 storageState 注入模式 |
| `keel.primitives` | L3 | TestRun 断言收集、勾稽四原语(diff_zero/conserved/delta_is/all_matched)、Saga 攻防追踪 |
| `keel.baseline` | L3 | 基线四步(快照→测试→还原→终态)，`guarded` 上下文管理器 + 漂移检测 |
| `keel.schemathesis` | L2 | `build_mini_spec` 只读 spec 生成(写端点不进 spec 防污染)、`run_fuzz` 封装与摘要解析 |
| `keel.report` | L5 | Finding(发现→证据→建议)、Severity 分级、Report.render_md / render_html |

## 设计约束

- **零依赖**：核心全标准库；换系统只改配置不改库
- **写保护**：受控探针必须配 restore（`guarded` 强制终态校验）；fuzz spec 只收只读端点
- **漂移优先**：基线不一致时告警而非默默跑错（源自回放缓存三态思想）
- Windows GBK 终端跑 fuzz 需 `PYTHONIOENCODING=utf-8`（`run_fuzz` 已内置）

## 下一步（v0.2 候选）

- [ ] invariants.yaml 加载器 + 编译为勾稽断言（contracts/ 规范落地）
- [ ] journeys 执行器（9 段骨架实例化）
- [ ] report.html 并入 CI 产物归档
