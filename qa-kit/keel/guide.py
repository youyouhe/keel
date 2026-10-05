"""keel.guide — 整体使用指南(MCP 工具 + CLI 子命令共用)

新 agent / 新人接入 keel-mcp 后的第一入口: 一篇看懂 Keel 是什么、
五步工作流、项目空间三个文件的写法、常见坑。
"""

GUIDE = """# Keel 快速上手(给 agent / 测试工程师)

## Keel 是什么
契约驱动的通用 B 端系统穿行测试框架。核心思想: **契约(invariants)先签收,
旅程(journey)管穿行, 报告管证据, issue 管闭环**。适用于 ERP/CRM/MES 等
有业务状态、有生命周期、有角色分工的事务型系统。

## 五步工作流(标准节奏)
1. `keel_project_create(name, env_dev, issue_repo)` — 建项目空间, 登记环境
2. **补契约** — 编辑 `projects/<A>/contracts/invariants.json`:
   把系统必须守恒的业务规则写成结构化条目(试算平衡/回款≤合同额/投入=产出+损耗)。
   每条: id/rule/check{left,op,right}/version/status。
   status: `confirmed`(已签收, 会被校验) / `draft`(草稿) / `unsourced`(待拍板)。
   check.left/right: 字面量 或 {"path":"a.b[0].c"}(从 context JSON 取值); op: ==/!=/<=/>=/abs<=
3. **写旅程** — 编辑 `projects/<A>/tests/journeys.py` 的 `build_journey(api)`:
   按 9 段骨架(SKELETON)注册 Step, 每个 Step 是 `fn(run) -> None`, 用
   `run.check(名, bool, 证据)` 断言。api 是已配认证的 Client, `api.as_role("xx")` 切角色。
   **注意: 新项目默认模板调 /api/v1/health, 必须换成你系统的真实端点!**
4. `keel_journey_run(project)` — 跑全量或 `--section J3` 按段; 报告落 reports/, 状态更新
5. `keel_issue_sync(project, dry_run=false)` — 失败项自动开 GitHub issue(幂等去重)
   `keel_report_render(project)` — 最新报告转 HTML
   `keel_status_get(project)` — 随时查上轮结果/历史绿率

## project.json 关键字段
- `env.dev`: 被测系统基地址
- `issueRepo`: "owner/repo" — issue_sync 的目标仓
- `envAuth`: 认证配置, 四种类型(journeys 里 `api.as_role("key")` 切角色):

  **demo-login 型**(演示系统):
  ```json
  {"type":"demo-login","path":"/api/v1/auth/demo-login","roleField":"roleCode"}
  ```

  **credentials 型**(真实产品 B 端, CRM 即此):
  ```json
  {"type":"credentials","path":"/api/v1/auth/login",
   "accounts":{"admin":{"username":"13800000001","password":"{env:CRM_PWD}"}},
   "tokenField":"token","roleField":"user.roleCode",
   "roles":{"admin":"R01"}}
  ```
  password 支持 `{env:VAR}` 环境变量占位(E4, 不落盘)。
  roles 表存在时登录后校验角色, 不匹配报 ROLE_MISMATCH(E2)。
  **loginBody 模板**(P1 推荐): 当登录 API 字段不叫 username 时, 用模板映射:
  `"loginBody": {"phone": "{username}", "password": "{password}"}`
  占位符 {username}/{password} 替换为 accounts 对应值; 模板键名=实际发送字段。
  旧方式 `usernameField: "phone"` 仍兼容(仅改发送键名)。

  **static-token 型**(预签发 API key):
  ```json
  {"type":"static-token","tokens":{"admin":"eyJ...","viewer":"eyJ..."}}
  ```

  **custom 型**(SSO/验证码等长尾):
  ```json
  {"type":"custom"}
  ```
  journeys.py 顶层定义: `def login(api, key) -> (token, roleCode)`。
  Keel 调钩子取 token, 后续请求自动携带; 401 时自动重登一次(E1)。

  ⚠ 未配 envAuth 时 as_role 报 ENV_AUTH_MISSING(E3), 不做静默 fallback。

## Client API 参考(journeys.py 里的 api 对象)
- 获取角色客户端: `R02 = api.as_role('key')` — 返回**独立副本**(多角色互不干扰)
- 请求方法: `api.get(path, params={})` / `api.post(path, body={...})` / `api.put` / `api.delete`
  - 也支持 requests 风格: `api.post(path, json={...})`
- 响应对象 `r`: `r.status`(精确 HTTP 状态码, 201/204 不归一化) ·
  `r.data`(解析后的 JSON) · `r.json`(等价 r.data, 属性非方法) · `r.ok`(2xx)
- 预期失败探针: `err = api.try_('POST', path, body=...)` —
  非 2xx 返回 `err.status / err.code / err.message`; 2xx 返回 None。
  注意: v0.10 起 4xx/5xx **不再抛异常**, 直接 `r.status` 断言即可, try_ 可不用
- 分段注册: `api.step("J1 线索", "建档", fn)` — 段名自由, 连续同名自动合并,
  `--section` 过滤用子串匹配段名
- 报工: `run.check(名, bool, 证据)` / `run.diff_zero / conserved / delta_is / all_matched`

## 常见坑
- **信任边界(必读)**: `keel_file_put` 可写 `tests/journeys.py`——而 journeys.py 会被
  Keel 动态 import 执行。因此 Bearer token 持有者 = 可在 Keel 服务器上执行任意代码。
  仅限可信局域网使用; token 即写权限, 不要泄露给不信任的一方。
- journeys.py 模板端点是占位, 必须先改
- envAuth 没配 → 全部请求 401
- issue_sync 需先跑过 journey_run(有报告才能同步)
- contract_verify 需 `--context ctx.json`(系统快照), 契约 left/right 的 path 从中取值
- 争议仲裁: 实现与契约不符 → 默认实现错(缺陷); 设计认为契约该改 → 走变更评审

## 分层心智模型
契约(L1, 判对错的标尺) → 通道(L2, REST/MCP/UI) → 原语(L3, 勾稽/基线)
→ 旅程(L4, 9 段骨架) → 报告(L5, 发现→证据→建议)。
"""


def get_guide(section: str = "") -> str:
    if not section:
        return GUIDE
    key = section.lower()
    for head in (f"## {section}", f"## {key}"):
        idx = GUIDE.find(head)
        if idx >= 0:
            nxt = GUIDE.find("\n## ", idx + 1)
            return GUIDE[idx:nxt if nxt > 0 else None]
    return f"未知章节 {section!r}; 可用标题原文: Keel 是什么/五步工作流/常见坑/分层心智模型"
