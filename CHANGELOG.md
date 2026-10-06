# 更新日志（CHANGELOG）

本项目所有显著变更记录于此（格式参考 Keep a Changelog）。日期即 git 提交日期，
完整轨迹见 `git log`（提交历史同时作为开发过程证据）。
工具数 / 测试数 / 性能数字的唯一来源见 `docs/口径速查表.md`。

## [Unreleased]

### 新增
- 开源治理文件：LICENSE（Apache-2.0）/ CONTRIBUTING / SECURITY / 本文件

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
