# Keel Frontend · 契约与报告查看器

零构建单文件静态页（`index.html`），本地渲染无网络请求。

## 用法

1. 浏览器直接打开 `index.html`（或 `python -m http.server` 托管）
2. 拖入 qa-kit 产物：`Report.to_json()` 的 report.json（必选）+ InvariantSet 导出的 invariants.json（可选）
3. 即得：统计卡 / 契约不变量状态(confirmed·draft·unsourced) / 断言明细 / 缺陷与观察

内置"载入演示数据"；冒烟验证见内部试点（Playwright 1.8s 通过）。
