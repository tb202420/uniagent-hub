# UniAgent Hub — 部署指南

> 版本：v1.0 · 2026-09-26 · 配套：`README.md`（快速开始）· `docs/api.md`（接口）· `docs/demo_script.md`（演示）
> 本文覆盖：环境要求、两种启动方式（Python 直跑 / Docker Compose）、配置项、离线模式、健康检查与故障排查。

---

## 1. 环境要求

| 项 | 最低要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10/11（开发与演示实测） | Linux/macOS 理论兼容（未列入验收范围） |
| Python | 3.12+（实测 3.14） | PATH 上的 Store shim 可能损坏，用 `py` 启动器 |
| 内存 | ≥ 1.5 GB（核心栈） | 含 LLM 环节另计显存（见 §6） |
| 网络 | 出网可选 | 断网用 `-Offline` 模式，核心功能等价 |
| 依赖 | `pip install -r requirements.txt` | 全部锁定版本（fastapi 0.141.1 / uvicorn 0.54.0 / pydantic 2.13.5 / paho 2.1.0 / httpx 0.28.1 等） |

可选组件：
- **本地 LLM**：[Ollama](https://ollama.com) + 量化模型（实测 Gemma-4-26B 3-bit，11GB，需 ≥16GB 显存）；
- **Docker 部署**：Docker Engine + Compose v2（比赛部署路径，本地开发不需要）。

## 2. 端口清单

| 端口 | 服务 | 模式 |
|---|---|---|
| 8020 | Hub 核心（MCP Gateway，`POST /mcp`） | 演示默认（`demo_start.ps1` 固定）；手动启动默认 8000 |
| 18080 | 审计面板（Web） | 演示默认 |
| 11434 | Ollama 本地模型 | 可选（LLM 环节） |
| 1883 / 8899 | 本地 MQTT broker / 本地 Mock 天气 API | 仅 `-Offline` 模式 |
| 8000 / 18083 | Hub（Docker 路径）/ EMQX Dashboard | Docker Compose |

> 端口被占用时：Hub 用 `--port` 改，面板用 `--port` 改；8020 的由来是本机 8000 被 VirtualBox 占用（见 dev_log）。

## 3. 方式一：Python 直跑（主路径，比赛现场）

### 3.1 一键全栈（推荐）

```powershell
# 在线模式：Hub + 温度模拟器(31°C) + 空调模拟器 + 审计面板 + REST 预热 + 就绪自检
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1

# 含 LLM 加分环节：额外预热本地 Ollama（加载权重 + 常驻显存）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Ollama

# 断网降级模式：本地 MQTT broker(amqtt) + 本地 Mock 天气 API
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -Ollama

# 彩排/无人值守：日志落 logs/*.log，不弹控制台窗口
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -Ollama -LogToFile
```

脚本自动完成 P1-P7（启动核心 → 双模拟器 → REST 预热 → 面板 → 自检 → LLM 预热），
输出"全部就绪，可以开始演示"即为成功，**无需任何手动配置**。

常用参数：`-Port`（Hub 端口）、`-InitTemp`（初始温度，默认 31，须 >28 才触发降温工作流）、
`-NoDashboard`、`-Offline`、`-Ollama`、`-LogToFile`。

### 3.2 手动分步（开发调试）

```powershell
py main.py --port 8020                                          # Hub 核心
py -m adapters.mqtt_adapter.simulator --init-temp 31            # 温度模拟器
py -m adapters.mqtt_adapter.sim_ac                              # 空调模拟器
py -m web.audit_dashboard --hub http://127.0.0.1:8020 --port 18080   # 审计面板
py -m agent.llm_agent --script --url http://127.0.0.1:8020      # Agent（脚本模式）
```

LLM 模式（三选一）：

```powershell
# A. 本地 Ollama（现场演示推荐：不依赖外网）
py -m agent.llm_agent --ollama --url http://127.0.0.1:8020 --goal "会议室太热了，帮我降温到 26 度"

# B. 云端 API（OpenAI 兼容：DeepSeek / 百炼）
$env:LLM_API_KEY = "<你的 Key>"
py -m agent.llm_agent --url http://127.0.0.1:8020 --goal "会议室太热了，帮我降温到 26 度"

# C. 确定性脚本降级（零依赖兜底）
py -m agent.llm_agent --script --url http://127.0.0.1:8020
```

## 4. 方式二：Docker Compose（比赛部署 / 环境复现）

```powershell
docker compose -f deploy/docker-compose.yml up -d --build
```

拉起两个服务：

| 服务 | 镜像 | 说明 |
|---|---|---|
| `emqx` | emqx/emqx:5.8 | 私有 MQTT broker；healthcheck（`emqx ping`）就绪后 Hub 才启动；Dashboard http://localhost:18083（admin / uniagent） |
| `hub` | 本地构建（`deploy/Dockerfile.hub`） | MCP Gateway :8000；环境变量注入私有 broker 地址与 topic 前缀；`hub_data` 卷持久化 SQLite |

Agent 不容器化，宿主机直跑（`py -m agent.llm_agent --url http://127.0.0.1:8000 ...`）。

> **如实说明**：本机 Docker 引擎当前故障（daemon 500），Compose 路径未在本机完成端到端验证，
> 作为比赛部署预案保留；现场演示一律走 §3 Python 直跑主路径（该路径已 3 轮彩排 8/8 验证）。

常用命令：`docker compose -f deploy/docker-compose.yml logs -f hub`（看日志）、`... down -v`（停止并清数据卷）。

## 5. 配置项（环境变量）

| 变量 | 默认 | 作用 |
|---|---|---|
| `HUB_MQTT_BROKER` | `mqtt://broker.emqx.io:1883`（直跑）/ `mqtt://emqx:1883`（Compose） | MQTT broker 地址 |
| `HUB_TOPIC_PREFIX` | `uniagent-hub-rxyc` | 设备注册/状态 topic 前缀，多实例隔离用 |
| `LLM_API_KEY` | 空 | 云端 LLM（OpenAI 兼容）Key；不设则本地 Ollama 或脚本降级 |
| `HUB_DASH_USER` / `HUB_DASH_PASS` | 空（关闭认证） | 审计面板 Basic Auth（公网暴露时务必启用） |
| `HUB_API_TOKEN` | 空（关闭鉴权） | 设置后 `/mcp` 与 `/workflows/recent` 需 Bearer Token；鉴权开启时权限由服务端裁决（认证=admin、未认证=read） |

模型侧参数（演示关键，勿随意改动，依据 `docs/evidence/` 实测）：
`num_ctx=16384`（默认 4096 会截断提示词；65536 挤爆 16GB 显存）、采样温度 `0.0`
（0.3 时数值保真 0/5）、`num_predict` 显式设置、`MAX_CALLS_PER_ROUND=1`（强制串行）。

## 6. 健康检查与验收

| 检查 | 命令 | 预期 |
|---|---|---|
| Hub 存活 | `curl http://127.0.0.1:8020/healthz` | `{"status":"ok"}` |
| 工具注册 | `tools/list`（见 api.md） | 演示档 14 个（软件档 11 + 温室模拟 3）；全量档 22 个（14 + 硬件档 8） |
| 断电恢复 | 重启 Hub → `tools/list` | 工具自动恢复（SQLite） |
| 审计面板 | http://127.0.0.1:18080 | 概览/审计/工作流三页 200 |
| 全栈自检 | `py scripts/demo_warmup.py` | 5 项检查全 ✓ |

## 7. 故障排查

| 症状 | 原因与处置 |
|---|---|
| 启动脚本报端口占用 | 换 `-Port`；8020 之外的占用进程用 `netstat -ano \| findstr <端口>` 找 PID |
| `python` 命令无输出/挂起 | Windows Store shim 损坏，改用 `py`；导入 paho 挂起见 dev_log（WMI 桩已内置） |
| MQTT 无消息 / 模拟器掉线 | 只重启该模拟器窗口（retain 注册消息自动重注册，Hub 无需重启）；公共 broker 抖动属正常，比赛建议 `-Offline` |
| `get_weather` 首次 4-5s | 冷连接正常；启动脚本已自动预热，命中缓存 <10ms |
| LLM 幕连接失败/超时 | `-Ollama` 汇总表会标"未就绪(降级)"；Agent 自动三级降级照常演示；Ollama 串行排队，**勿并发调用** |
| 首次 LLM 请求 >300s | `num_ctx` 误设过大挤爆显存，确认 16384；关闭占显存进程 |
| Docker daemon 500 | 本机引擎故障已知，走 Python 直跑主路径 |

## 8. 数据与安全

- 注册表与审计双写：SQLite（`data/`，WAL）+ JSONL（`data/audit.jsonl`），重启自动恢复；
- CLI 执行硬约束：`subprocess(argv, shell=False)` + 参数白名单，禁止字符串拼接；
- REST 适配器：SSRF 拦截私有地址、API Key 环境变量脱敏、响应 1MB 截断、只读缓存 300s；
- 面板公网暴露前务必启用 Basic Auth（§5）；
- **设 `HUB_API_TOKEN` 开启网关鉴权**（§5）：网关默认监听 `127.0.0.1`；设置后 `/mcp` 与
  `/workflows/recent` 需 Bearer Token（401=未授权，JSON-RPC 错误码 -32001），鉴权开启时权限由
  服务端裁决（认证=admin、未认证=read）。
