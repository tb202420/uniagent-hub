# UniAgent Hub — 产品需求文档（PRD）

> 版本：v0.1（阶段 0 冻结） · 日期：2026-09-25 · 状态：已评审

## 1. 背景与问题

当前 AI Agent 调用外部工具的方式碎片化严重：

- **物联网设备** 通过 MQTT/私有协议接入，Agent 无法直接理解；
- **CLI 工具** 需要 `subprocess` 拼接命令，无类型、无校验、有注入风险；
- **REST API** 每个服务一种鉴权与参数风格；
- 三者各自为政，Agent 每接入一种资源就要写一套集成代码。

**结论**：Agent 生态缺少一个"协议无关的通用工具集成层"。

## 2. 产品定位

UniAgent Hub 是一个**通用 AI Agent 工具集成平台**，是"AI 世界的 USB-C 接口"：

> 无论背后是传感器、命令行工具还是云服务，通过 UniAgent Hub 插上来就能用。

核心主张（比赛主论点）：

1. **一规范多类型**：设备、CLI、REST、脚本用同一套 `UniSpec` 描述能力；
2. **Agent 只认识 MCP**：上层 Agent 只通过 `tools/list` / `tools/call` 调用一切；
3. **安全内建**：参数校验、命令注入防护、权限、审计从第一行代码开始；
4. **无状态网关**：可水平扩展、可部署到 Serverless 平台。

## 3. 目标用户与核心场景

| 用户 | 场景 |
|---|---|
| Agent 开发者 | 通过 MCP 统一调用异构工具，无需关心底层协议 |
| 设备/服务提供方 | 设备上线即注册（MQTT 发布 UniSpec），工具自动发现 |
| 运维/管理员 | 通过审计界面查看调用链路、拦截恶意参数 |

## 4. 演示场景（已确定）

**主场景：智能办公环境管理**

| 资源类型 | 具体工具 | 演示动作 |
|---|---|---|
| IoT 设备（MQTT） | 温度传感器 `get_temperature` | Agent 查询当前温度 |
| IoT 设备（MQTT） | 空调 `ac_control` | 温度 > 28°C 时自动开启 |
| CLI 工具 | `git_status` | 查询仓库 Git 状态 |
| REST API | 天气查询 `get_weather` | 获取城市天气（open-meteo 免费 API，无需 Key） |
| 工作流 | `run_workflow` | 温度高 → 开空调，一次调用完成 |

**备用场景**：开发环境自动化（`git_status` → `file_search` → 生成报告）。

**降级方案**：
- 硬件掉线 → 用 MQTT 模拟器（Python 脚本）顶替；
- 外网 API 不可用 → 本地 Mock 服务；
- 大模型不可用 → 固定 Agent 脚本 + 工具白名单。

## 5. 比赛评分点映射

| 评分点 | 如何在产品中体现 | 对应模块 |
|---|---|---|
| 创新性 | UniSpec 统一抽象、CLI 双向生成、无状态网关 | UniSpec / CLI Adapter / Gateway |
| 工程完整性 | 注册中心持久化、适配器模式、模块化分层 | ToolRegistry / Adapters |
| 安全性 | 参数白名单、`shell=False`、权限分级、审计日志 | Guard Module |
| 演示效果 | 5 分钟场景化演示、审计界面可视化 | Web Dashboard / Demo |

## 6. 范围界定

**In scope（MVP → 阶段 2）**
- UniSpec v0.1 + 注册中心（SQLite 持久化）
- CLI / MQTT-IoT / REST / 本地脚本 / 数据库 五类适配器（B9 批次补齐数据库）
- MCP Gateway（`tools/list`、`tools/call`、`server/discover`）
- Guard v1（权限 + 参数校验 + 审计日志）

**Out of scope（可降级）**
- 工作流引擎（阶段 3）
- 可视化审计前端（阶段 3）
- Prometheus 指标（阶段 3，可选）
- 多租户 / 多 Agent 会话隔离（后续）

## 7. 非功能需求

| 项 | 要求 | 参考 |
|---|---|---|
| 性能 | 单工具调用 < 500ms | 参考 IoT-MCP 205ms |
| 安全 | 注入/越权/超时/限流全部拦截并记录 | Guard |
| 可用性 | 硬件/网络异常有降级方案 | 模拟器 / Mock |
| 部署 | Docker Compose 一键启动，2GB 内存可跑 | 约 1.5GB 内存 |
| 可观测 | 每次调用有 `trace_id` 与完整审计 | structlog |

## 8. 成功指标

- 阶段 2 末：≥ 5 个工具注册（2 IoT + 2 CLI + 1 REST），统一 `tools/list` 输出；
- 恶意参数（如 `; rm -rf`）100% 拦截；
- 演示脚本连续 3 次无失败。

## 9. 里程碑总览

| 阶段 | 周期 | 目标 |
|---|---|---|
| 阶段 0 | 2–3 天 | 需求冻结、UniSpec v0.1、接口契约、Compose 雏形 |
| 阶段 1 | 第 1–2 周 | CLI + MQTT 最小闭环 |
| 阶段 2 | 第 3–5 周 | 多类型适配、Guard v1、5 工具注册 |
| 阶段 3 | 第 6–7 周 | 工作流编排、Guard v2、可观测性 |
| 阶段 4 | 第 8 周 | 演示、文档、答辩 |
