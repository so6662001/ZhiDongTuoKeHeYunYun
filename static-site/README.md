# 静态页面演示（static-site）

把平台所有功能做成**纯静态 HTML 页面**，数据已内置在页面里，无需后端、无需联网即可直接打开预览。

## 如何查看

直接用浏览器打开任意 `.html` 文件即可（双击或拖入浏览器）：

| 页面 | 文件 | 内容 |
|---|---|---|
| 经营总览 | `index.html` | KPI、经营漏斗、AI 副驾今日待办、模块入口 |
| 客户主权看板 | `dashboard.html` | 私域/战略客户、"我的客户被谁访问过"审计（防撬客）、战略客户保护开关 |
| 智能获客 | `acquisition.html` | 公域供需撮合、AI 线索评分、行情钩子裂变卡片 |
| 智能客户运营 | `operation.html` | 客户分层矩阵、自动触达队列、AI 销售副驾驶简报 |
| 智能转化与风控 | `conversion.html` | 转化漏斗、智能建议报价、智能锁价、信用评分与账期、弃单挽回 |

页面之间通过左侧导航栏互相跳转。`site.css` 为共享样式。

## 效果截图

预渲染截图位于 `screenshots/`，可在 PR 或文档中直接查看：
`index.png` / `dashboard.png` / `acquisition.png` / `operation.png` / `conversion.png`。

## 与可交互版本的区别

- 本目录（static-site）：**纯静态**，数据写死在 HTML 里，用于快速预览视觉与信息架构，零依赖。
- `prototype/frontend/`：**可交互**版本（Vue 3），通过 REST API 调用真实引擎（鉴权/多租户/持久化），需启动 `uvicorn api.app:app`。

两者视觉风格一致；静态版用于"看效果"，交互版用于"跑流程"。
