# UniAgent Hub — 通用 AI Agent 工具集成平台

> **AI 世界的 USB-C 接口**：无论背后是传感器、命令行工具还是云服务，插上来就能用。
>
> 科创比赛参赛项目 · 阶段 0-3 已完成（**216 项测试全部通过** · 工具全量 22 个（软件档 11 + 硬件档 8 + 温室模拟节点 3）/ 演示档 14 个 · 5 类适配器已实装 + WebSocket 1 类规划 · 工作流闭环）·
> 演示级就绪（一键启动 + 断网降级 + 3 次彩排 8/8 + 本地 LLM 接入）·
> 改进方案第 1 批已落地（FastMCP 4 前端 / 元工具渐进发现 / 生命周期与插件 / Schema 签名与审计哈希链 / 硬件测试档）

## 核心主张

1. **一规范多类型** — 设备 / CLI / REST / 脚本 / 数据库统一用 `UniSpec`（v0.3.0）描述能力；
2. **Agent 只认识 MCP** — 上层 Agent（LLM 或脚本）仅通过 `tools/list`、`tools/call` 调用一切，无法区分背后资源类型；
3. **安全内建** — 参数校验、命令注入防护、权限分级、限流、审计从第一行代码开始，Guard 管道对 LLM 与脚本一视同仁；
4. **无状态网关** — 自研 JSON-RPC 2.0 路由（零 MCP SDK 依赖），可水平扩展。

## 演示场景：智能办公环境管理

温度传感器（MQTT）→ 查询温度 → 工作流判断 >28°C → 查天气 → 自动开空调降温（MQTT 写操作回执确认），辅以 Git 状态（CLI）、天气查询（REST）、文件统计（脚本）。

一次 `run_workflow("office_cooling")` 完成 3 步闭环（实测约 4s）：
`get_temperature(29.9°C) → get_weather → ac_control(on, 27°C)`。

## 快速开始（Python 直跑，主路径）

### 一键演示（推荐，含 5 分钟演示全栈）

```powershell
# 一条命令拉起：Hub(8020) + 温度模拟器(--init-temp 31) + 空调模拟器 + 审计面板(18080)
#             + 自动预热 get_weather + 就绪检查
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1

# 含 LLM 环节（加分项）：额外预热本地 Ollama 模型（加载权重 + 常驻显存）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Ollama

# 断网降级模式（本地 MQTT broker + 本地 Mock 天气 API，核心功能完全不变）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -Ollama

# 彩排 / 无人值守（写 logs/*.log，不弹窗口）+ 五幕自动评分
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -LogToFile
python -m scripts.demo_rehearsal --label "复现"
```

> 演示端口固定 **8020**（本机 8000 常被其他进程占用）；演示脚本见 `docs/demo_script.md`（v1.2 · 7 幕 300s 配时），
> 录屏流程见 `docs/demo_video_guide.md`，彩排记录见 `docs/test-reports/demo_rehearsal_log.md`，
> 过程证据索引见 `docs/evidence/README.md`。

### 手动分步启动（开发调试）

```bash
# 0) 环境：Python 3.12+（实测 3.14）
pip install -r requirements.txt          # 运行时依赖（版本已锁定，复现演示环境）
pip install -r requirements-dev.txt      # 开发/测试/文档辅助（含上面全部 + pytest 等）

# 1) 启动 Hub（MCP Gateway :8000，SQLite 持久化自动恢复）
python main.py

# 2) 另开两个终端，启动 IoT 模拟设备（公共 broker，免本地安装）
python -m adapters.mqtt_adapter.simulator --init-temp 31   # 温度传感器
python -m adapters.mqtt_adapter.sim_ac                     # 空调控制器

# 3) Agent 上场（三选一）
python -m agent.llm_agent --ollama   # LLM 模式·本地 Ollama：自然语言目标 → ReAct 闭环（无需 API Key）
python -m agent.llm_agent            # LLM 模式·云端：需 API Key（见下）
python -m agent.demo_agent           # 链路演示：工具发现 → 调用 → 注入/越权/限流拦截

# 4) 审计界面（浏览器打开）
python -m web.audit_dashboard      # http://127.0.0.1:18080
```

**开启鉴权（可选，安全批次）**：设置 `HUB_API_TOKEN` 后，`/mcp` 与 `/workflows/recent`
需携带 `Authorization: Bearer <token>`（缺失/错误返回 401 / JSON-RPC -32001）；网关默认只监听 127.0.0.1：

```powershell
$env:HUB_API_TOKEN = "your-secret-token"
python main.py                # 再次启动，鉴权生效
```

**LLM 模式（可插拔，SUP-01）**：任何 OpenAI Chat Completions 兼容服务均可接入
（DeepSeek / 阿里百炼兼容模式 / Ollama / vLLM），设置环境变量即可，零代码改动：

```bash
# A. 本地 Ollama（推荐现场演示：不依赖外网，无需 API Key）
python -m agent.llm_agent --ollama --url http://127.0.0.1:8020

# B. 云端 API
set DEEPSEEK_API_KEY=sk-xxx        # 或 LLM_API_KEY / DASHSCOPE_API_KEY
set LLM_BASE_URL=https://api.deepseek.com/v1   # 可选，默认 DeepSeek
set LLM_MODEL=deepseek-chat                      # 可选
```

> LLM 只负责"决策"（选工具、定参数），所有调用必须经 Gateway Guard 管道 ——
> 平台安全不依赖 LLM 可靠性。三级降级链保证演示永不中断：
> 原生 `tool_calls`（ReAct）→ 提示词 JSON 计划 → 确定性脚本模式。

**本地 Ollama 实测要点（gemma-4-26B-A4B IQ3_XXS · RTX 5060 Ti 16GB）**：
温度必须 0.0（temp=0.3 时数值保真 0/5、会编造数值）；上下文由 Agent 按请求下发
（16384 稳定，**勿设 `OLLAMA_CONTEXT_LENGTH=65536`**，会挤爆 16GB 显存）；
不可并发调用（Ollama 串行排队）。详见 `docs/demo_script.md` §7 与 `docs/dev_log.md` §九。

**Docker Compose 部署（比赛环境备选）**：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
# Gateway: http://localhost:8000/mcp · EMQX UI: http://localhost:18083 (admin/uniagent)
```

## 仓库结构

```
uniagent-hub/
├── core/                  # 核心层
│   ├── unispec/           #   UniSpec v0.3.0 模型与校验
│   ├── registry/          #   工具注册中心（SQLite WAL 持久化）
│   ├── gateway/           #   MCP 网关（JSON-RPC 2.0 + Guard 横切管道）
│   ├── guard/             #   参数校验 / 注入拦截 / 三维限流 / 审计
│   ├── workflow/          #   工作流引擎（拓扑排序 + 自研安全表达式，零 eval）
│   └── cli_gen/           #   CLI 反向生成器
├── adapters/              # 适配器层（统一 discover/list_tools/call_tool 协议）
│   ├── cli_adapter/       #   CLI 工具（subprocess shell=False + 白名单，跨平台模板）
│   ├── mqtt_adapter/      #   IoT 设备（自动发现 + 状态缓存 + 写回执）
│   ├── rest_adapter/      #   REST API（OpenAPI 导入 + SSRF 防护）
│   ├── script_adapter/    #   本地脚本（路径沙箱）
│   └── database_adapter/  #   数据库（SQLite 只读查询 + 受限写，B9）
├── agent/                 # Demo Agent（LLM 可插拔 + 脚本降级）
├── web/audit_dashboard/   # 审计 Web 界面（FastAPI + 纯 HTML）
├── generated_cli/        # CLI 反向生成产物（8 个脚本）
├── scripts/              # 一键演示启动 / 预热 / 彩排评分 / Ollama 预热 / 本地 broker / Mock API
├── demo_fallback/        # 演示降级素材（预录视频位 + 应急预案）
├── deploy/                # Dockerfile.hub + docker-compose.yml
├── docs/                  # PRD / 规范 / 架构 / API 契约 / 测试报告 / 证据 / 演示脚本
├── tests/                 # 216 项测试（unit / integration / 适配器契约 / 安全）
└── main.py                # 启动入口
```

## 已注册工具（演示档 14 个；全量档 22 个 = 软件档 11 + 硬件档 8 + 温室模拟节点 3）

| 工具 | 类型 | 权限 | 说明 |
|---|---|---|---|
| `get_temperature` / `get_humidity` | IoT (MQTT) | read | 温湿度传感器（模拟器，状态 retain） |
| `get_ac_state` / `ac_control` | IoT (MQTT) | read / write | 空调状态查询与控制（写回执确认） |
| `git_status` / `file_search` | CLI | read | Git 状态 / 文件搜索（subprocess 沙箱，Linux=find / Windows=where） |
| `get_weather` | REST | read | 天气查询（open-meteo，只读缓存 300s） |
| `file_summary` | 脚本 | read | 目录文件统计（路径白名单） |
| `db_query` / `db_execute` | 数据库 | read / write | SQLite 演示库只读查询 / 受限写（动词白名单，B9） |
| `run_workflow` | 工作流 | write | 预定义蓝图编排（office_cooling / office_status） |
| `get_soil_moisture` / `get_light_intensity` | 温室模拟节点（ESP32 SIL） | read | 土壤湿度 / 光照强度（`sim_esp32_greenhouse`，MQTT 状态缓存） |
| `control_pump` | 温室模拟节点（ESP32 SIL） | write | 水泵控制（QoS1 + request_id 写回执） |

> 硬件档（4 类真实硬件，另 8 个）：摄像头 2（`capture_image`/`detect_motion`）、智能插座 2
> （`plug_get_state`/`plug_set_power`）、手机节点 2（`get_phone_battery`/`get_phone_temperature`）、
> PC 监控 2（`get_system_cpu`/`get_system_memory`），经档位隔离（独立 SQLite）与演示档分离。
> 温室模拟节点由 `sim_esp32_greenhouse.py`（设备 id `irrigation_01`）提供，配合工作流
> `smart_irrigation`（读土壤湿度 → 读光照 → 条件开泵）验证浇水闭环（模拟器实测 0.23s / 1.30s / 100ms）。

## 安全设计（Guard 管道，所有调用必经）

```
存在性(1001) → 权限(1003) → 限流(1004) → 参数校验/注入拦截(1002/1007) → 执行 → 审计
```

- 权限粒度到能力级：`cap.permissionLevel > (readOnly ? read : 资源级声明)`，支持设备级加固；
- CLI 执行 `subprocess(argv, shell=False)`，参数正则白名单，杜绝命令注入；
- 限流三维（tool × caller × scope）滑动窗口，工作流内部步骤独立配额；
- 恶意参数（`; rm -rf /` 等）拦截率 100%，全部留痕审计（SQLite + JSONL 双写）；
- **安全批次（2026-10-04）**：网关默认监听 `127.0.0.1`；设 `HUB_API_TOKEN` 后 `/mcp` 与
  `/workflows/recent` 需 `Authorization: Bearer <token>`（401=未授权，JSON-RPC 错误码 -32001）；
  鉴权开启时权限由服务端裁决（认证=admin、未认证=read，客户端 `permission_level` 仅作提示）；
  SSRF 增强（域名先 DNS 解析校验 + 非常用端口拒绝，`HUB_REST_CHECK_DNS=0` 可关 DNS 校验）；
  审计面板全部输出 HTML 转义。

## 扩展能力（改进方案第 1 批，2026-10-03 · 全部可选开关，默认行为不变）

| 能力 | 启用方式 | 说明 |
|---|---|---|
| **FastMCP 4 协议前端** | `python main.py --gateway fastmcp` | 协议层交给 FastMCP（streamable HTTP，客户端连 `http://host:port/mcp`，协商 2026-07-28）；执行/安全/审计仍走自研网关（`selfdev` 为默认与回退路径） |
| **渐进式工具发现（4 元工具）** | `--meta-tools` / `HUB_META_TOOLS=1` | `discover_tools` / `get_tool_schema` / `execute_tool` / `refresh_registry`；`execute_tool` 透传完整 Guard 管道 |
| **适配器插件（entry_points）** | 自动加载（`--no-plugins` 关闭） | 第三方适配器包在 `uniagent_hub.adapters` 组声明入口点；`/healthz` 汇总各适配器健康状态（生命周期回调） |
| **工具清单签名（工具投毒防护）** | `HUB_ATTESTATION_KEY=<PEM>` | SHA-256 内容哈希（默认）+ Ed25519 签名；`server/attestation` RPC / `scripts/attestation.py` |
| **审计哈希链（防篡改）** | `HUB_AUDIT_CHAIN=1` | 逐条 `rec_hash` 链接，`scripts/attestation.py audit-verify` 校验；SQLite 自动迁移 |
| **硬件测试档** | 见 [docs/hardware/](docs/hardware/hardware_test_plan.md) | 4 个测试（摄像头/插座/手机/PC）× 4 类适配器；含 mock 预演与调试探针 `scripts/hardware_probe.py` |

## 文档索引

| 文档 | 说明 |
|---|---|
| [docs/prd.md](docs/prd.md) | 产品需求与比赛评分点映射 |
| [docs/unispec.md](docs/unispec.md) | 统一能力描述规范 v0.3.0（冻结） |
| [docs/architecture.md](docs/architecture.md) | 架构设计与 ADR（含 Guard 顺序设计说明） |
| [docs/api.md](docs/api.md) | MCP Gateway + 适配器接口契约 v0.5（含变更记录） |
| [docs/demo_script.md](docs/demo_script.md) | 5 分钟演示脚本 v1.2（7 幕 300s 配时 + LLM 加分环节 + 9 项评分表 + 降级方案） |
| [docs/demo_video_guide.md](docs/demo_video_guide.md) | 演示视频录制流程（逐幕操作 + 讲解词 + 时间分配 + 人工操作清单） |
| [docs/test-reports/demo_rehearsal_log.md](docs/test-reports/demo_rehearsal_log.md) | 3 次彩排记录（均 8/8）与问题清单 |
| [docs/evidence/README.md](docs/evidence/README.md) | 过程证据索引（每个文件对应 dev_log 哪张表 + 复现命令） |
| [docs/evidence/phase4_offline_verification.md](docs/evidence/phase4_offline_verification.md) | 断网降级可用性验证证据 |
| [docs/dev_log.md](docs/dev_log.md) | 开发日志（30+ 工程问题与解决过程，含 §九 本地 LLM 接入） |
| [docs/roadmap.md](docs/roadmap.md) | 阶段任务看板与验收标准 |
| [docs/deployment.md](docs/deployment.md) | 部署指南（环境与端口 / 一键与 Docker Compose / 配置项 / 健康检查 / 故障排查） |
| [docs/design/improvement_plan.md](docs/design/improvement_plan.md) | 改进方案实施计划（第 1 批落地明细 + 后续路线图 / 时间节点 / 资源 / 风险回退） |
| [docs/hardware/hardware_test_plan.md](docs/hardware/hardware_test_plan.md) | 硬件测试环境配置方案（4 个测试：摄像头 / 智能插座 / 手机 / PC 系统） |
| [docs/hardware/hardware_test_cases.md](docs/hardware/hardware_test_cases.md) | 硬件兼容性测试用例（TC-1x~4x + TG 通用性）与 A/B/C 评估标准 |
| [docs/hardware/hardware_test_record_template.md](docs/hardware/hardware_test_record_template.md) | 硬件测试数据记录模板（环境 / 逐用例 / 性能 / 问题 / 证据 / 结论） |
| [docs/defense_script.md](docs/defense_script.md) | 答辩讲稿（逐页口播 + 15 秒电梯陈述 + 13 题问答库 + 演示衔接） |
| [docs/答辩PPT.pptx](docs/答辩PPT.pptx) | 答辩演示文稿 14 页（与讲稿 P1-P14、演示脚本七幕对齐） |
| docs/design/ · docs/test-reports/ · docs/evidence/ | 各阶段设计 / 测试报告 / 过程证据 |
