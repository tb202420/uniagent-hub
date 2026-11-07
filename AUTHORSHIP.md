# AUTHORSHIP · 模块贡献与出处说明

> 本文件按"本人独立完成 / 参考规范或开源实现改写 / 直接使用第三方 / AI 辅助"四类
> 声明各模块出处，供评审与开源使用者核对。开发窗口：**2026-09-26 至 2026-11-07**
> （完整开发历史首提交 `35b884b`，在青少年科创成果"两年内完成"窗口内）。
> 公开仓库提交区间：[cfef89d … 43f0dfa]（2026-10-05 首个开源快照至 v2.0 收口）；
> v3.0 三层控制台批次（2026-11-07）另见 `CHANGELOG.md` 与 tag
> `v3.0-three-layer-console`；逐阶段开发过程另见 `docs/dev_log.md` §1–§16。

## 一、本人独立完成（设计 + 实现 + 测试）

| 模块 | 说明 | 主要落点（公开区间） |
|---|---|---|
| UniSpec 规范与校验模型 | 七要素结构、Pydantic 模型、v0.3.1 六类型枚举 | cfef89d（随首快照） |
| 自研 JSON-RPC 网关 | tools/list·call·server/discover、Bearer/JWT 鉴权、权限服务端裁决 | cfef89d → 40982ce |
| Guard 安全管道 | 存在性→权限→限流→参数校验/注入拦截→审计；错误码 1001–1007/1999 | cfef89d → 40982ce |
| 审计哈希链 / Schema 签名 | SHA-256 内容哈希、Ed25519 可选签名、链式防篡改 | cfef89d |
| 工作流引擎 | Kahn 拓扑排序、零 eval 表达式（含三元）、并行分支（opt-in）、事件流 | cfef89d → 40982ce |
| 六类适配器 | MQTT/CLI/REST/Script/Database（首快照）+ WebSocket（40982ce 补全） | cfef89d → 40982ce |
| Agent 插件宿主 | AgentAdapter 接口、entry_points 发现、内置 script/ollama/openai-compat | 40982ce |
| 短期 JWT 令牌 | HS256、10 分钟时效、caller/perm/tools 白名单 | 40982ce |
| 管理界面 | 纯 HTML 审计面板 + JSON API；React 19 双模 SPA（简易/专家、场景确认、ELK 布局） | 40982ce → ed0a1d7 |
| ESP32-S3 固件 | UniSpec 契约对齐模拟器、DHT22 位带直驱（无外部库）、真机编译/烧录/e2e 实测 | 40982ce → 71d0fd1 |
| 可观测与 CI | /metrics 四指标；CI 6 job + pip-audit + CodeQL；v3.0 OTel GenAI SemConv 本地 span + SDK 双写 | 40982ce → f4a3031 |
| **v3.0 三层控制台** | 事件总线（WS + 轮询兜底）、HITL 审批闸门 + 审计落链、交互终端 token/输入 Guard/会话、A2A 最小端点、RAF 批处理 hook、span 瀑布图、审批卡片、Zustand 接管状态机、问题陈述首页 | v3.0 批次（2026-11-07） |
| 测试体系 | **321 项**（v2.0 基线 261 + v3.0 批次 60；分布见 `docs/测试报告_v3.0.md`） | 全区间 |

## 二、参考规范 / 开源实现后自研（非抄袭）

| 项 | 参考 | 本项目自研部分 |
|---|---|---|
| UniSpec 设计 | W3C WoT Thing Description（概念启发） | 面向 MCP 的七要素结构与 JSON Schema 校验独立设计 |
| 网关端点语义 | MCP 官方规范文档 | 路由/鉴权/裁决实现全部自研；FastMCP 仅作可选前端 |
| 元工具渐进发现 | 社区 fastmcp-gateway 模式（思路） | 自研实现（discover/schema/execute/refresh 四元工具） |
| MQTT 模拟器/固件 | paho / PubSubClient 官方示例用法 | 行为契约、状态机、回执匹配全部自研 |
| OTel 追踪 | OpenTelemetry GenAI SemConv 字段规范 | 本地 span 存储、事件总线联动、双写桥接自研 |
| 交互终端 | xterm.js 前端 API、POSIX pty 系统编程 | token 安全、输入 Guard、会话管理、接管状态机自研 |

## 三、直接使用的第三方（版本锁定，见 requirements.txt / Cargo.lock）

FastAPI、uvicorn、Pydantic、FastMCP 4、paho-mqtt、httpx、websockets、PyJWT、
prometheus-client、cryptography、opentelemetry-sdk / -exporter-otlp /
-instrumentation-fastapi、pytest（Python）；React 19、Vite、@xyflow/react、
elkjs、@xterm/xterm、@xterm/addon-fit、zustand（前端）；ArduinoJson 7、
PubSubClient 2.8（固件）；Tauri 2（桌面壳框架）。

## 四、AI 辅助开发（如实声明）

调试、重构、测试用例补全与文档撰写过程中使用了 AI 编程助手；
**系统架构、模块设计、实验设计与全部技术决策由本人确定**，
所有代码经本人审核、全部结论经 321 项自动化测试与实测证据验证。

## 引用

本项目为青少年科技创新大赛参赛作品（Apache-2.0 开源）。引用请注明出处：
`tb202420/uniagent-hub`，并附本文件的模块贡献说明。
