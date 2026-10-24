# 更新日志（CHANGELOG）

本项目所有显著变更记录于此（格式参考 Keep a Changelog）。日期即 git 提交日期，
完整轨迹见 `git log`（提交历史同时作为开发过程证据）。
工具数 / 测试数 / 性能数字的唯一来源见 `docs/口径速查表.md`。

## [Unreleased]

### 新增
- 开源治理文件：LICENSE（Apache-2.0）/ CONTRIBUTING / SECURITY / 本文件
- **材料收口批次（2026-10-24 第三批，路线 B）**：研究报告全文统一 261 口径
  （六类适配器与真机端到端写入正文 4.9/5.8/表 2/表 15，附录 A 三表：18 增强证据 /
  19 三态清单 / 20 测试演进；docx 重导 291 段 20 表）；口径速查表新增 §6 全材料
  统一总表（测试演进 / 已实现·脚手架·roadmap 三态 / 真机数字定义对照 / 届次提醒）；
  答辩讲稿升级 261 口播 + 材料收口六题必练问答；dev_log 补 §15/§16；
  增强证据包 v20_enhancement_batch_20261024.txt（插件清单 / JWT 三态 / 并行 3 轮对比 /
  metrics 采样 / CI 快照 / 桌面档 linker 状态如实记录）
- **桌面档外壳本地编译打通（同日补充）**：VS Build Tools 就位后，build-local.cmd
  注入 MSVC 环境绕过 winget 未注册 vswhere 实例的坑，cargo release 16.6s 编译通过
  （9.4MB exe）；修复 tauri.conf.json 位置与 icon.ico 缺失两处脚手架问题；
  口径仍为"外壳已编译验证"，NSIS 打包与运行实测未做
- **v2.0 补全批次（2026-10-24 第二批）**：
  - Agent 插件宿主：AgentAdapter 统一接口 + `uniagent_hub.agent_adapters` entry_points
    发现；内置 script（确定性规则意图解析）/ ollama（原生 tool_calls 串行闭环，
    温度 0）/ openai-compat（DeepSeek 等兼容端点）三插件；CLI `python -m agent.plugins`
  - 短期 JWT 令牌（§3.6）：HUB_AUTH_MODE=jwt，HS256、10 分钟过期、绑定 caller/perm/tools、
    禁止会话认证；自研网关与 FastMCP 前端同语义；签发 CLI scripts/issue_token.py
  - 工作流引擎 v2.0：蓝图级 parallel 并行分支（拓扑层并发，默认串行口径不变）、
    三元表达式 `cond ? a : b`、DAG 最长路径深度上限 20、执行事件流 /workflows/events
  - 可观测：/metrics Prometheus 端点（调用/拦截/延迟/工作流四组指标，软依赖降级）
  - 场景模板 scenes.yaml（5 个）+ SPA 简易模式（一键场景卡片、写操作确认卡片、
    事件进度 chips、ELK 自动布局带手工回落、简易/专家双模切换）
  - 桌面档脚手架 desktop/（Tauri 2 最小外壳 + capabilities 最小权限 +
    PyInstaller sidecar spec + Actions Desktop Build 手动工作流）
  - CI 强化：pip-audit（advisory）与 CodeQL（周巡）工作流
- **第 6 类适配器 WebSocket**（UniSpec v0.3.1 `websocket_stream`）：订阅缓存读 / 写发送 /
  断线指数退避重连；默认不加载（`HUB_WS_CONFIGS` 启用，演示档口径不变）；含真实回环集成测试
- **React 管理控制台初版**（`web/spa`，React 19 + React Flow 12）：工具注册中心 / 工作流 DAG /
  安全中心 / 审计日志四页；Dashboard 新增 JSON API（`/api/stats|audit|tools|workflows|workflow-defs|audit/verify`）
- 网关新增 `GET /workflows/defs`（蓝图结构，SPA 可视化数据源；受 Bearer 保护）
- **ESP32-S3 温室固件真机轨**：UniSpec 契约与模拟器逐字段对齐（契约回归测试 6 项），
  DHT22 位带直驱 / BH1750 / 土壤 ADC / 继电器 / 看门狗 / 断线退避 / OTA 可选 / TLS 可选；
  编译（RAM 15.2%/Flash 24.4%）与真机烧录启动实测通过
- **真机端到端联调实测（2026-10-24）**：自动发现 / 命令→回执 avg 152ms（5/5）/
  自动停泵 5.1s 精确自停 / 经 Hub Guard 全链路 100ms / 审计含 schema_hash；
  证据生成器 `scripts/real_device_e2e.py` 入库（`--rounds 20` 可复跑采集参赛口径数据）；
  凭据经 `src/secrets.h`（已 gitignore）注入，仓库不含真实 WiFi/MQTT 信息
- 硬件档新增 2 个灌溉策略蓝图：光照感知灌溉（白天判定）与三连干旱告警灌溉

### 修复
- 硬件测试活文档（test_plan / test_cases）的工具数预期与现口径对齐
  （22 = 软件档 11 + 温室模拟节点 3 + 硬件专测 8；未叠加模拟器时为 19），
  消除与其他文档及实测数据的跨文档冲突

### 变更
- 根目录规划类 txt 归档至 `docs/`（开发路线 / 技术栈完善方案）
- `agent/demo_agent.py` 的仓库 / 搜索目录默认值改为当前工作目录（去除开发机绝对路径）
- CLI 反向生成 README 与 LLM 探针提示词中的示例路径改为可移植写法

### 移除（仅移出版本库，本地保留用于材料再生成）
- 含个人信息的比赛材料生成脚本（答辩 PPT / 研究报告 docx / 申报材料生成）

## [2026-10-05] P2 加固批次

### 新增
- FastMCP 前端 Bearer 覆盖：`--gateway fastmcp` 在 `HUB_API_TOKEN` 下同样 401 / -32001，
  前端经受信中继执行（身份取自 `HUB_FASTMCP_CALLER` / `HUB_FASTMCP_PERMISSION`）
- 审计 SQLite 表改为自增主键并自动迁移老库（防同 trace_id 静默覆盖历史审计记录）
- REST 适配器复用 `httpx.Client` 连接池，新增 `on_shutdown` 释放
- Dashboard：概览统计 SQL 聚合、审计时间转本地时区、新增 schema_hash 列
- `pytest.ini` 与 GitHub Actions CI（ubuntu / windows × Python 3.12 / 3.14）
- 测试 +13 项 → 全量 216 项全部通过、0 跳过

### 修复
- CLI / 脚本适配器子进程非 UTF-8 输出导致解码崩溃（`errors="replace"`）
- MQTT 断线重连指数退避（`reconnect_delay_set` 1s→30s）

## [2026-10-04] P0/P1 安全批次 + ESP32 温室模拟器

### 新增
- Bearer Token 鉴权与权限服务端裁决（防客户端自报越权）；网关默认绑定 127.0.0.1
- REST SSRF 增强：域名先解析再校验 IP 归属、公网仅 80/443
- 审计面板全量 HTML 转义；审计查询 SQL 层 caller 筛选
- ESP32 温室节点 Python MQTT 模拟器（软件在环 SIL；真机固件骨架双轨保留），
  实测浇水闭环 1.30s / 写回执 100ms / 自动发现 0.23s
- 4 类真实硬件测试工件（USB 摄像头 / 智能插座 / 手机传感器 / PC 系统监控）

### 修复
- 网关限流 key 由服务端派生；测试基线 203 项全绿；全库口径统一
  （全量 22 / 演示档 14 工具，5 类适配器已实装 + 1 类规划）

## [2026-10-04] 改进方案第 1 批

### 新增
- FastMCP 4 协议前端（双协议时代按连接协商，自研网关保留为默认与回退路径）
- 4 元工具渐进式工具发现（discover_tools / get_tool_schema / execute_tool / refresh_registry）
- 适配器生命周期回调（on_startup / on_health_check / on_shutdown）+ entry_points 第三方插件发现
- Schema 签名（SHA-256 + Ed25519，`HUB_ATTESTATION_KEY`）与审计哈希链（`HUB_AUDIT_CHAIN=1`）

## [2026-09-26] 阶段 0-4 全链路交付

### 新增
- 阶段 0-1：UniSpec 规范冻结 → ToolRegistry → CLI 适配器 → 自研 JSON-RPC 网关
  → Demo Agent → MQTT 模拟设备（MVP 垂直链路）
- 阶段 2：SQLite 持久化 + REST / 脚本适配器 + server/discover + 适配器契约测试
- 阶段 3：WorkflowEngine（拓扑排序 + 零 eval 表达式 + 数据管道）+ Guard v2
  （限流 / 注入拦截）+ CLI 反向生成 + 审计 Web 面板
- 阶段 4：一键演示启动 + 断网降级方案 + 3 次彩排 8/8；本地 LLM 接入
  （Ollama 原生 tool_calls + 三级降级链）
- 12 项 ERR / 3 项 SUP 集中检查修复
