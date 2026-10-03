# qa-kit 抽包路线（第一步）

从起源项目的长期回归资产提炼，下个系统第一天即可 import。

| 模块 | 内容 | 来源 |
|---|---|---|
| client/ | login/token/角色矩阵、req 封装(错误码语义断言 400/403/409×code) | 每轮测试脚本 |
| primitives/ | P() 断言、勾稽原语(diff=0/A=B/双向Δ/allMatched) | 域级轮测 |
| baseline/ | 基线四步(前置快照→测试→还原→终态校验)+漂移检测 | EPF 穿行 |
| channels/ | channel-rest / channel-mcp(tools/call) / channel-ui(编排 playwright) | 三通道方法论 |
| report/ | 发现→证据→建议 + saga 追踪 + HTML 汇报生成 | 全部报告 |
| schemathesis/ | mini-spec 模板 + st 调用封装 | 一期实战 |

技术栈：Python 先行（Schemathesis/pytest 同栈）；v0.1 时再评估 TS 契约类型共享。
