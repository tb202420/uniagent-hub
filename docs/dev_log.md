# UniAgent Hub 开发日志

> 用途：研发过程记录（可作为研究报告"实验过程"附件与答辩证据）。
> 更新日期：2026-10-04（最后更新：新增第十三章 · 全面检查与 P0/P1 安全批次）

## 一、阶段 0：需求冻结与架构定稿（已完成）

- 交付：`docs/prd.md`、`docs/unispec.md`（UniSpec v0.1 冻结）、`docs/architecture.md`、`docs/api.md`（接口契约冻结）、`docs/roadmap.md`（任务看板）、`deploy/docker-compose.yml`（雏形）。
- 验收：✅ 接口冻结、✅ 数据流 `Agent → Gateway → Guard → Adapter → 资源` 画清。

## 二、阶段 1：MVP 垂直链路（已完成）

### 2.1 实现清单

| 模块 | 文件 | 要点 |
|---|---|---|
| UniSpec 模型 | `core/unispec/models.py` | Pydantic + id/名称/类型-协议配对/超时/限流校验，`mcp_tools()` 生成 MCP 定义 |
| 工具注册中心 | `core/registry/registry.py` | 注册/注销/解析/适配器归属（内存版） |
| Guard 参数校验 | `core/guard/validation.py` | JSON Schema 子集 + 注入白名单（默认拒 shell 元字符） |
| 审计 | `core/guard/audit.py` | JSONL 落盘 `data/audit.jsonl` + 内存 ring |
| CLI 适配器 | `adapters/cli_adapter/` | YAML 注册、`{placeholder # 描述}` 模板 → JSON Schema、`subprocess(argv, shell=False)`、超时、`allowed_commands` 白名单 |
| MQTT 适配器 | `adapters/mqtt_adapter/` | 设备自动发现（`uniagent/register`）、状态缓存、`get_*` 工具 |
| MQTT 模拟器 | `adapters/mqtt_adapter/simulator.py` | 模拟 ESP32：发布 UniSpec（retain） + 周期温度/湿度 |
| MCP Gateway | `core/gateway/server.py` | FastAPI + JSON-RPC 2.0：`POST /mcp`（initialize/ping/server/discover/tools/list/tools/call）+ `GET /healthz` |
| Demo Agent | `agent/demo_agent.py` | 自研 MCP 客户端，工具发现 + 调用 + 注入演示 |

### 2.2 测试与实测数据

- **单元/集成测试**：47 个全部通过（UniSpec / 模板解析 / Guard 注入防护 / Registry / Gateway / MQTT Mock broker）。
- **CLI 链路 E2E**（真实 git 命令）：`git_status` 成功，延迟 93ms；注入 `x; rm -rf /` 被 1007 拦截并写入审计。
- **MQTT 链路 E2E**（公共 broker `broker.emqx.io:1883` + Python 模拟设备）：
  - 设备自动发现成功，`tools/list` 注册 4 个工具（2 CLI + 2 IoT）；
  - `get_temperature` 返回 24.9°C、`get_humidity` 返回 56.0%（缓存读取，0ms）；
  - 未知参数 `room` 被 Guard 1002 拦截（参数校验横切所有类型工具）；
  - 审计落盘包含每次调用（trace_id / caller / args / guard_result / latency）。

### 2.3 阶段 1 验收清单

- [x] Agent 不知背后是 CLI 还是 MQTT，只通过 MCP 调用成功
- [x] 恶意参数 `; rm -rf` 被拦截（1007）
- [x] 每次调用有 trace_id 审计记录
- [x] 单工具延迟 < 500ms

## 三、工程问题与解决（比赛材料"设计难点"章节素材）

| # | 问题 | 根因 | 解决 | 比赛材料表述 |
|---|---|---|---|---|
| 1 | Store 版 Python 无法运行脚本 | WindowsApps 别名指向的 Store shim 失效（exit 9009） | `py.exe` 定位真实安装 `C:\Users\admin\AppData\Local\Programs\Python\Python314` | "选用官方 Python 3.14，规避 Store 版沙箱限制" |
| 2 | `python -m venv` 后无 pip | Python 3.14 venv ensurepip 异常 | `python -m ensurepip --upgrade` 引导 | — |
| 3 | Docker 引擎 500 | Docker Desktop Linux 引擎未就绪/损坏 | 阶段 1 采用公共 MQTT broker + amqtt 备份，EMQX 保留为比赛部署方案 | "采用公共 broker 作为本地开发降级方案，EMQX 保留为比赛部署方案" |
| 4 | `import paho.mqtt.client` 挂起 5~30s+ | `platform.system()` 触发 WMI 查询（Win11 已移除 wmic，subprocess 等待） | 导入前将 `platform._wmi_query` 替换为快速抛错，强制走 `ver` 回退 | "通过兼容性适配将 paho 导入从 30s+ 优化到 <0.1s" |
| 5 | `-WindowStyle Hidden` 下重型导入挂起 | 隐藏控制台 + 特定 DLL/导入链问题 | 改用 `-NoNewWindow` 启动 | "定位 PowerShell 启动参数与重型导入的兼容性问题" |
| 6 | E2E 404 | `httpx` 将 `base_url` 路径与请求路径拼接成 `/mcp/mcp` | 客户端 base_url 不含路径后缀，RPC 统一发往 `/mcp` | "修复客户端 base_url 约定，避免路径重复拼接" |
| 7 | 审计未落盘 | Gateway 默认使用无文件路径的 `AuditStore()` | 默认改为文件版 `default_logger`（`data/audit.jsonl`） | "审计从内存 ring 升级为文件落盘，保证可追溯" |
| 8 | MQTT 连接阻塞 Hub 启动 | `client.connect()` 阻塞（公共 broker 网络不可控） | `connect_async()` + `loop_start()` + on_connect 回调订阅 | "网关启动不受外部网络阻塞（非阻塞连接设计）" |
| 9 | 回调签名不匹配导致发现失败 | `CallbackAPIVersion.VERSION2` 回调为 5 参签名 | 更新 on_connect/on_disconnect 签名 | "适配 MQTT 客户端回调 API 版本" |
| 10 | 消息回调内动态 subscribe 丢消息 | paho 回调线程内 subscribe 存在竞态 | 连接时通配符订阅 `uniagent/devices/+/state`，注册不做动态订阅 | "订阅策略：通配符预订阅 + 单次保留注册" |
| 11 | 一次性注册消息丢失 | 异步连接时序（QoS0 注册先于 Hub 订阅） | 注册消息 `retain=True`，broker 为新订阅者补发 | "设备注册采用保留消息，自动发现不丢失" |
| 12 | 未知参数校验仅覆盖 CLI | Guard 参数校验只在 CLI 适配器内 | 参数校验上移至 Gateway Guard 管道（横切所有适配器），适配器保留纵深防御 | "参数校验横切：所有类型工具统一走 Guard 管道" |

## 四、遗留项（阶段 2 处理）

1. **Docker Compose 可运行验证**：本机 Docker 引擎 500，EMQX 容器未跑通 → 比赛部署环境验证。
2. **MQTT 真实硬件（ESP32）**：当前用 Python 模拟器，真机仅演示。
3. **ToolRegistry SQLite 持久化**：阶段 2。
4. **REST / 脚本适配器**：阶段 2。

## 五、阶段 2：一规范多类型（已完成 2026-09-25）

### 5.1 实现清单

| 模块 | 文件 | 要点 |
|---|---|---|
| SQLite 持久化 | `core/registry/store.py` | tools + audit 表、WAL 模式、线程安全；Registry 同步落库 + 启动恢复；审计 JSONL+SQLite 双写 |
| REST 适配器 | `adapters/rest_adapter/` | OpenAPI 导入（本地/URL，YAML/JSON，$ref 解析）→ MCP Tool；SSRF 防护/API Key 脱敏/超时/1MB 截断 |
| 脚本适配器 | `adapters/script_adapter/` | subprocess 沙箱 + 路径白名单（scripts/ 下，拒 ../ 逃逸）；stdout JSON 结构化返回 |
| 契约测试 | `tests/adapters/contract_test.py` | 四类适配器统一：未知参数 1002/注入 1007/越权 1003/审计必写 |
| server/discover | `core/gateway/server.py` | 增强：protocolVersion + supportedVersions + listChanged |

### 5.2 实测数据

- 测试：**79 个全部通过**（含阶段 1 的 47 项无回归）
- E2E：6 工具统一注册；`get_weather` 真实调用 open-meteo（北京天气）；`file_summary` 115ms
- 持久化：SQLite 5 资源落库（含 MQTT 自动发现设备）；审计可查询（tool + 时间范围）
- 重启恢复：Hub 重启后 tools/list 仍为 6 工具
- 安全横切：4 类适配器统一拦截未知参数/注入；越权 1003；SSRF 拦私有地址

### 5.3 新增工程问题与解决

| 问题 | 解决 |
|---|---|
| OpenAPI load_spec 对 Path 误判为 URL | 显式 isinstance(Path) 分支 |
| UniSpec id 允许中文字符（校验失败） | 生成 id 仅保留 ASCII alnum/._- |
| rateLimit "10/min" 不符合规范 | 按 UniSpec 枚举用 "10/m" |
| 脚本默认目录指向 configs/scripts | 改为适配器包内 scripts/（与 configs 平级） |
| 默认注入白名单缺 `:`（Windows 盘符被误拦） | DEFAULT_ARG_PATTERN 增加冒号，重测无回归 |

## 六、阶段 3：工作流编排 + Guard v2 + CLI 双向 + Web 可视化（已完成 2026-09-25）

### 6.1 实现清单

| 模块 | 文件 | 要点 |
|---|---|---|
| MQTT 写操作 | `adapters/mqtt_adapter/adapter.py` `_call_write` + `sim_ac.py` | publish(qos=1) → 回执等待（3s 超时不阻塞）；action enum + 温度范围约束走 Guard |
| 工作流引擎 | `core/workflow/engine.py` + `expr.py` + `workflows.yaml` | Kahn 拓扑排序、数据管道 `{{sN.output}}`、条件分支（自研安全解析器零 eval）、失败传播、递归防护、单工具调用上限 |
| Guard v2 | `core/guard/ratelimit.py` + Gateway | 滑动窗口限流（tool+caller+scope），1004；工作流整体限流 10/m；scope 隔离防误伤 |
| CLI 反向生成 | `core/cli_gen/generator.py` | MCP Tool → argparse+httpx 脚本 → `generated_cli/`，与 tools/call 等价 |
| 审计 Web | `web/audit_dashboard/` | FastAPI + 纯 HTML：概览/审计筛选/工作流链路；可选 Basic Auth |

### 6.2 实测数据

- 测试：**119 个全部通过**（阶段 1+2 无回归；新增表达式注入用例/限流/工作流/契约）
- E2E：9 工具（含 run_workflow）；一次 `run_workflow(office_cooling)` 3 步闭环
  （29.9°C → 天气 → 空调 on/27°C，3.97s）；限流 1004；CLI 8 脚本实跑成功；Dashboard 三页 200

### 6.3 新增工程问题与解决

| 问题 | 解决 |
|---|---|
| YAML 1.1 把裸 `on/off` 解析为布尔 | workflow args 中 action 加引号（PyYAML 陷阱） |
| 工作流步骤与外部调用挤占限流桶 | RateLimiter 增加 scope 维度，工作流内 `wf:<trace_id>` 单独计数 |
| 工作流内非字符串参数（bool）被模板替换误转字符串 | 仅对含 `{{` 的字符串做替换，其余值原样传递 |
| 依赖步骤失败后下游仍执行 | 失败传播：依赖 error/skipped → 本步骤 skipped |
| 浮点算术结果不满足 integer Schema | ac_control 温度改 number（16-30 范围仍强约束）；引擎整值浮点规整 |
| REST 公共 API 慢/抖动 | 只读响应 300s 缓存 |
| 工作流部分失败无明细 | `_call_workflow` 携带步骤明细 JSON + 错误码 1999 |

## 七、阶段 4 计划

演示与文档：5 分钟演示脚本（工具列表 → 单工具 → 工作流闭环 → 安全拦截 → CLI 反向生成 → 审计界面）、
研究报告/查新报告撰写、答辩 PPT、Docker Compose 一键部署（比赛环境 EMQX）、
12 月 1 日前提交材料（详见 docs/roadmap.md 阶段 4）。

## 八、最终检查与修复批次（2026-09-26）

全面自查发现 12 项问题（ERR-01~12）+ 3 项补充（SUP-01~03），经逐条评审确认后集中修复。
完整清单见 `docs/test-reports/final_check_report.md`。

### 8.1 修复内容

| 项 | 问题 | 修复 |
|---|---|---|
| ERR-03 | `get_ac_state` 被资源级 write 权限误伤（read 用户查询状态被 1003） | 权限公式升级为能力级粒度：`cap.permissionLevel ?? (readOnly ? "read" : 资源级)`；修复过程中发现并解决第二层缺陷——stateField 缺省时字段推断失败导致 1006，改为"推断键存在才取字段，否则返回完整状态对象" |
| SUP-03 | 公共 broker 上无前缀 topic 与他人流量冲突 | 全部 topic 加项目前缀 `uniagent-hub-rxyc/`（`HUB_TOPIC_PREFIX` 可覆盖），集中定义于 `adapters/mqtt_adapter/topics.py` |
| SUP-01 | Agent 层无真实 LLM，"AI 在哪"会被质疑 | `agent/llm_agent.py`：OpenAI 兼容可插拔 LLM（DeepSeek/百炼/Ollama 零代码切换）+ 无 Key 自动降级脚本模式；核心论点：LLM 只做决策，安全由 Hub Guard 保证，不依赖 LLM 可靠性 |
| ERR-09 | 依赖版本未锁定 | requirements.txt 全部锁定（fastapi 0.141.1 等 7 项） |
| ERR-02 | Dockerfile 缺失 | `deploy/Dockerfile.hub`（python:3.12-slim + 健康检查）；compose 移除未实现的 agent-demo，修正数据卷路径 |
| ERR-04/05 | api.md 与实现漂移（discover 结构 / run_workflow 动态 steps） | api.md 升 v0.2：discover 对齐实现；run_workflow 明确"预定义蓝图 + params"并记录设计理由；新增变更记录章节 |
| ERR-06 | unispec.md 示例 `10/min` 违反自身 Schema | 升 v0.2.0：修正示例、收录 stateField/paramPatterns/permissionLevel、topic 前缀协议、CHANGELOG |
| ERR-08 | 限流先于参数校验被疑为缺陷 | 经评审确认维持现状（资源保护优先，拦截率等价，审计不丢信息），设计说明写入 architecture.md ADR-3；测试改用独立 caller |
| ERR-07/11 | README 停留在阶段 0；演示稳定性无文档 | README 全面重写（Python 直跑主路径 + 9 工具 + 安全设计）；新建 `docs/demo_script.md`（init-temp 31 / REST 预热 / 降级方案 / 3 轮全绿标准） |
| ERR-01/SUP-02 | git 零提交，事后补提交的诚信风险 | 如实分 5 批提交（阶段 0→3 + 修复），不伪造历史时间戳；过程证据以 dev_log + evidence/ 时间戳文件为主，git 作为代码基线佐证 |

### 8.2 新增工程问题与解决

| 问题 | 解决 |
|---|---|
| 权限修复后 `get_ac_state` 仍失败（1006 状态无字段） | 字段推断改为"候选键存在于状态才取字段，否则返回完整状态对象"——单元测试先暴露问题再修复，回归测试锁定行为 |
| 测试用例共享 caller 触发限流污染断言 | 安全用例改用独立 caller 标识（perm-test-N） |

### 8.3 验收

- MQTT 相关 10 项测试全绿（含 4 项新增权限优先级回归测试）
- 全量测试见修复批次验证记录（fx-6）

## 九、本地 LLM 接入与适配（2026-09-26，演示级增强）

目标：把 Agent 层的 LLM 从"仅支持云端 API"扩展到"可本地部署"，摆脱对外网与 API Key 的依赖。
实测模型：`gemma4local:latest`（Gemma 4 26B-A4B IQ3_XXS，3-bit 量化，11GB），硬件 RTX 5060 Ti 16GB。

### 9.1 能力探针（先测量，再适配）

探针 `scripts/ollama_tool_probe.py`，用 Hub 真实 `tools/list`（9 工具）验证三条通道：

| 通道 | 结果 |
|---|---|
| Q1 Ollama 原生 `/api/chat` | **6/6 通过**（含"双字符串参数""引号赋值"两个已知易错用例） |
| Q2 OpenAI 兼容 `/v1` | 1/1 通过（`arguments` 为 JSON 字符串，需 `json.loads`） |
| Q3 提示词 JSON 计划 | 3/3 可解析，但**多步规划不稳定**（只返回首步）→ 仅作兜底 |

结论：原生 `tool_calls` 可用且能让 Agent 基于真实返回值逐步决策，故实现"原生优先 + 计划兜底 + 脚本保底"三级降级链。

### 9.2 本轮发现并修复的工程问题

| # | 问题 | 根因 | 解决 |
|---|---|---|---|
| 13 | `get_ac_state` 返回 Python repr（单引号）而非 JSON | Gateway `_finish` 用 `str(result.data)` 序列化 dict | 新增 `_to_text()`：dict/list 走 `json.dumps(ensure_ascii=False)` |
| 14 | **写操作返回陈旧回执**：连续两次 `ac_control(on)` 的第二次 0ms 返回上一次状态（旧 `request_id`/旧温度），"未确认本次命令却报成功" | `_call_write` 仅比对 `action` 字段，缓存中残留的同值状态被误判为本条命令的回执 | 回执判据改为 `request_id` 精确匹配（设备已回写该字段），不回声的设备退化为 action 匹配；新增 3 项单元测试锁定 |
| 15 | **Ollama 默认只加载 4096 上下文**（模型原生支持 262144） | Ollama 服务端默认值，`/api/ps` 可见 | 原生通道显式传 `options.num_ctx`。实测 65536 会挤爆 16GB 显存（13.4GB 占用、余 1.2GB，首次请求 >300s 超时），**16384 稳定**（12.36GB，余 2.5GB） |
| 16 | **模型陷入重复退化**：单轮吐出 67 个相同的 `get_temperature` 调用，撑满 token 后遗忘用户目标 | 上下文溢出截断最旧的 system 提示与目标 | 放大 `num_ctx` + 单轮调用数硬上限 + 相同调用复用结果不重复执行 |
| 17 | **原生通道无界生成导致超时**：单次请求可挂起 >120s | Ollama 原生 `options` 没有 `max_tokens` 默认值（OpenAI 通道有），模型退化时持续输出 | 显式设置 `num_predict=1024`；平均耗时从 91.3s 降到 12.3s |
| 18 | 模型输出泄漏模板控制 token：`thought\n<channel|>`、`>${thought}`、`<tool_call|><|tool_response>` | Gemma 在 Ollama 上的模板渲染残留 | `_clean_answer()` 统一剥离；剥离后无实质内容则视为无效结论并降级（避免把垃圾当结论打印） |
| 19 | **条件分支形同虚设**：模型在同一轮批量发 `get_temperature`+`ac_control`，**未观察结果就做条件判断**；实测"仅当超过 35 度才开空调"时一边开空调一边宣称"未达到 35 度" | 小模型不遵守提示词里的"每轮只调用一个工具" | 代码层强制串行（`MAX_CALLS_PER_ROUND=1`）；且**不能静默丢弃**超量调用——实测会反复重提导致耗尽轮数（3/3 复现），须在工具结果里附明确平台说明 |
| 20 | 参数命名陷阱（预判）：若工具参数名为 `type`/`description`/`properties`/`required`，Gemma 渲染器会静默丢弃 | — | 现有 9 工具参数名均无冲突，已核验；作为约束记录在案 |
| 21 | 并发调用 Ollama 超时 | Ollama 串行排队处理请求 | 明确"不可并发调用"，测试脚本注明须串行执行 |

### 9.3 温度实验（对量化模型的影响远超预期）

同一模型、同一目标（"会议室太热了，帮我降温到 26 度"），各 5 次：

| 指标 | temp = 0.3 | temp = 0.0 |
|---|---|---|
| 原生模式成功 | 3/5 | **5/5** |
| 正确调用 ac_control | 4/5 | **5/5** |
| 数值转述保真 | 0/5 | **4/5** |
| 平均耗时 | 12.3s | 22.6s |

结论：温度不只影响"格式稳定性"，更直接决定模型会不会**编造数值**、会不会**谎称做了未做的操作**。
故默认温度定为 0.0（确定性优先），代价是耗时略增。

### 9.4 诚实结论与演示定位

- LLM 模式定位为**可选增强**，演示主路径仍为确定性脚本模式（零外部依赖、结果可复现）；
- 三级降级链保证"模型不可用/超时/输出垃圾"任一情况下演示都不中断；
- 条件分支场景验证 3/3 通过（串行强制后）；无条件目标 5/5 通过（temp=0.0）；
- 3-bit 量化模型在多步工具调用上的可靠性是**模型能力上限**，非平台缺陷 —— 平台侧
  Guard（校验/权限/限流/审计）与 LLM 可靠性完全解耦，这是"安全不依赖 LLM"主张的实证。
---

## 十、阶段 4 收尾：答辩材料补齐与研究报告 Word 定稿（2026-09-26）

### 10.1 阶段 4 核查结论（对照 docs/开发路线.txt）

- 已具备：5 分钟演示脚本（demo_script.md v1.2，七幕 300s 配时）、备用方案三件套
  （demo_fallback/ 预录视频规范 + demo_start.ps1 -Offline 断网模式 + 本地 Ollama）、
  文档（README / unispec / api / architecture / 四份测试报告）、研究报告 Word 版；
- 缺口（本次补齐）：答辩 PPT、答辩讲稿、独立部署指南。

### 10.2 本次新增交付

- **docs/答辩PPT.pptx**（14 页，pptxgenjs 生成）：深青主题 + 微软雅黑，复用研究报告
  6 张图件（图 1 架构），2 张原生图表（LLM 温度对比 0.3→0.0、单工具延迟实测），
  数据全部取自实测记录（126 测试 / 9 工具 / 100% 拦截 / 3.97s / 22.6s / 3 轮彩排 8/8）。
  验证：LibreOffice 渲染 14 页逐页目视 + python-pptx 程序化 QA（14 slides / 292 shapes /
  无占位符残留）；生成脚本存 scripts/build_ppt.js 可再生。
- **docs/defense_script.md**：8 分钟逐页口播讲稿（含 5 分钟压缩版标注）、15 秒电梯陈述、
  13 题高频问答库（含"是不是套壳""量化误差可信吗"等刁钻题）、演示衔接与答辩纪律。
- **docs/deployment.md**：环境要求 / 端口清单 / Python 直跑与 Docker Compose 双路径 /
  环境变量 / 健康检查 / 故障排查；如实标注 Docker Compose 未在本机端到端验证
  （本机 daemon 500，作为比赛部署预案）。
- README 文档索引 +3 行（deployment / defense_script / 答辩PPT）。

### 10.3 研究报告 Word 版定稿（9 项格式与字体问题修复）

- 目录域失效 → 35 个标题补大纲级别 + 目录预填充（35 条页码 0 错配）+ updateFields；
- 页脚 PAGE 域非法嵌套（fldSimple 在 run 内）→ 重建合法结构，页码自 p2 起显示，
  封面经 titlePg 隐藏页码；
- 编号列表全文共用计数器（4.5 节显示 6/7/8）→ 6 组各自独立 numId + startOverride=1；
- 西文宋体 → Times New Roman（1500 处 rFonts，代码保留 Consolas）；
- 正文左对齐 → 两端对齐（127 段）；参考文献改悬挂缩进；
- 12 表补 tblHeader/cantSplit、表题与图 keepNext；封面空段合并为精确高度占位（位置还原 ≤0.5pt）；
- 元数据补齐（标题/作者/日期）。备份：docs/研究报告_backup.docx。
- 验证：LibreOffice 渲染 29 页逐页目视 + 全文规范化比对（正文逐字一致）+
  postcheck（剩余 1 项 TOC 提示为启发式误报：本文档用大纲级别而非 Heading 样式）。

### 10.4 环境注记

- 本机无管理员权限 + 系统待重启，LibreOffice MSI 安装两次 1603 失败；
  改用 `msiexec /a` 管理解包落 D:\LO_extract（免安装可用），
  渲染统一走 `soffice.com -env:UserInstallation=file:///D:/LO_profile`；
- pip 可用：pymupdf / python-pptx 已入 3.14 环境。

### 10.5 遗留事项（如实）

- 预录视频需赛前人工录制（demo_fallback/README.md 有规范与命名约定）；
- v1.2 七幕新结构需重新彩排（历史 3 次 8/8 对应 v1.1 五幕，计划 9.27）；
- Docker Compose 路径待 Docker 引擎恢复后端到端验证；
- 本节改动未提交 git（等用户确认后一并提交）。

---

## 十一、改进方案第 1 批（2026-10-03）

依据 `项目改进方案/` 两份文档实施；研究报告类文档按要求**推迟到硬件测试完成后**修改。

### 11.1 协议层：FastMCP 4 兼容前端（opt-in）

- 安装 fastmcp==4.0.10（依赖**纯增量**，不降级既有锁定版本；附带 cryptography/PyJWT/jsonschema）；
- `core/gateway/fastmcp_server.py`：协议层交给 FastMCP（streamable HTTP），工具以 **4 个元工具**
  暴露；执行仍走自研网关（Guard 全链路 + 审计 + 递归防护）；
- 自研网关保留为**默认与回退路径**（`--gateway selfdev`）；`--gateway fastmcp` 启用前端；
- 过程注记：FastMCP 4 不支持 `**kwargs` 动态函数、也无 `as_proxy`，最终采用
  "静态签名元工具 + 动态执行透传"组合（**不用 exec/eval 生成函数**，延续项目零 eval 原则）。

### 11.2 渐进式工具发现（Meta-Tools）

- `core/gateway/meta_tools.py`：discover_tools / get_tool_schema（模糊匹配）/ execute_tool
  （透传完整 Guard：1001/1002/1003/1004/1007 语义与 tools/call 一致）/ refresh_registry（增删摘要）；
- 开关：`--meta-tools` / `HUB_META_TOOLS=1`（默认关闭，兼容既有客户端与演示链路）。

### 11.3 适配器生命周期 + entry_points 插件

- 5 个适配器新增 on_startup / on_health_check / on_shutdown；`/healthz` 新增 adapters 汇总
  （实测 8 个适配器实例健康状态含 broker 连接、设备数、脚本根、DB 可达）；
- `core/adapters/plugins.py`：`uniagent_hub.adapters` 组 entry_points 自动加载（失败不阻断启动）。

### 11.4 安全增强：Schema 签名 + 审计哈希链

- `core/guard/attestation.py`：SHA-256 内容哈希（默认）+ Ed25519 签名（HUB_ATTESTATION_KEY）；
  新增 `server/attestation` RPC 与 `scripts/attestation.py`（hashes / genkey / audit-verify）；
- 审计哈希链（HUB_AUDIT_CHAIN=1）：pre_hash/rec_hash 逐条链接，verify_chain 可检出篡改并定位；
  SQLite audit 表自动迁移（ALTER TABLE 增量列）；审计记录默认携带 schema_hash。

### 11.5 硬件测试准备（4 个测试）+ 两处历史缺陷修复

- 交付：camera_capture.py / hardware_tests.yaml / smart_plug.yaml / system_monitor.yaml /
  mock_plug_api.py / mock_phone_sensor.py / workflows_hardware.yaml / hardware_probe.py（check/call/watch）；
- 修复 1（历史缺陷）：REST 适配器 requestBody 经 simplify_schema 丢失嵌套 properties →
  `body_*` 参数从未注册（POST 类接口不可用）；改为直接展开 + **JSON body 实际发送**；
- 修复 2：只读缓存对含写能力的设备 Spec 造成"写后读旧值"→ 缓存仅对
  "整份 Spec 全只读"（如天气 API）启用；
- 实测（硬件档）：19 工具 / 6 工作流；office_auto_light 闭环（15°C → 自动开插座 → 状态 power=true）；
  probe check（8 预期工具全在 + 5 只读探测 ✓）/ watch / call --permission write 全部通过。

### 11.6 验证与遗留

- pytest **175 passed**（第 1 批 +35，复查批次 +1）；新模块覆盖率 **91%**（目标 >80%）；整体 70%
  （缺口在 agent/llm_agent 等历史模块，列入批 2.5）；
- 环境注记：本地 amqtt broker 通配订阅会多投递 retained 消息（EMQX/公共 broker 无此现象），
  probe watch 已加 topic 前缀过滤；平台按 topic 前缀分发不受影响；
- 遗留：硬件实测为人工操作（模板/探针已备）；前端/Tauri/CI/长稳见 `docs/design/improvement_plan.md` §4；
- 本批改动未提交 git（等用户确认后一并提交）。

### 11.7 硬件测试执行（无外部硬件用例，2026-10-03）

- 新增用例执行器 `scripts/hardware_test_run.py`（PASS/FAIL/SKIP 与用例编号一一对应，
  可复跑；后续接真硬件即回归工具）；`probe check` 默认探测集移除摄像头取景类工具
  （detect_motion 会开启摄像头，按"硬件操作交人工"约定不自动执行）；
- 执行结果：**20/20 通过、0 失败**（TC-2x 插座 mock、TC-3x 手机模拟器、TC-4x 全真、
  TC-15/35/25/34、TG-1~4）；TC-23 双分支（15.2°C 触发 / 24.9°C 跳过）均实测；
  待人工：TC-11/12/13（摄像头取景，本机检测到 3 个摄像头设备）；
- 执行期新修 2 项：`HUB_AUDIT_FILE` 审计档位隔离（原 JSONL 写演示审计文件）、
  `verify_chain` 混合文件兼容（跳过节前无链记录）；pytest **175 passed**；
- 存档：`docs/hardware/records/20261003_hardware_test.md`（整合报告）、
  `docs/evidence/hardware_test_20261003.txt`（原始输出 §[1]~§[9]）。

### 11.8 复查修复批次（2026-10-04，A/B/C 批）

- A1 `verify_chain` 改为**混合文件分段校验**：链段→关链期→再启链 不误报"篡改"，
  段间无链记录中性跳过（注明条数），篡改仍按全局下标定位（含新单测）；
- A2 元工具审计记录 schema_hash 回退到**元工具定义**（非空，语义统一）；
  `scripts/hardware_test_run.py` 的 TG-3 判据改按工具名分组（排除元工具），
  TG-3/TG-4 任意顺序执行结果一致（含新单测）；
- A4/B3 FastMCP 前端 transport 改 **streamable-http**，真实 HTTP 冒烟通过：
  协商 2026-07-28 / 4 元工具 / execute_tool 透传 Guard 返回真实 git 输出 /
  审计两条记录（git_status + execute_tool）schema_hash 均非空；
  证据 `docs/evidence/fastmcp_http_smoke_20261004.txt`（注意：该前端无 /healthz，
  服务端点 POST /mcp，客户端需连 `http://host:port/mcp`）；
- B1/B2/A3 文档统一：测试数 175、opencv 5.0.0、REST 连接池列入改进路线批 5；
- C3 确认保留测试档数据（`audit_hardware.jsonl`/`uniagent_hardware.db`）作复现证据
  （记录附件已注明）；C1 笔误空目录 `D:\projec\UniAgent Hub\scripts` 待人工删除；
- 回归：pytest **180 passed** 全绿。

---

## 十二、ESP32 温室节点改用 Python MQTT 模拟器（2026-10-04，重大口径变更）

### 12.1 决策

原文档曾以"已接入 ESP32-S3 真实硬件完成浇水闭环"表述。经复核，**真机链路从未实测**（固件下载受阻、器件未到位），
该表述不可靠。项目决策：**全面改用 Python MQTT 模拟器替代真实 ESP32 硬件**作为演示与测试主路径，
真机固件降为**后续可选轨**。

- 硬件口径统一为：**4 类真实硬件**（USB 摄像头 / 智能插座 / 手机节点 / PC 系统监控）
  **+ 1 类模拟节点**（ESP32 温室）；
- 真机固件骨架 `docs/hardware/firmware/esp32/`（`platformio.ini` + `src/main.cpp`）**双轨保留**：
  "骨架已预留，当前以模拟器为准"，**不声称已烧录或已实测真机**；
- 复用既有范式：自阶段 1 起即以 `simulator.py` / `sim_ac.py` 等 Python MQTT 模拟器验证协议链路，
  本次将同一范式扩展到温室灌溉节点，**核心代码 0 行修改**（仅新增设备模拟器与工作流蓝图）。

### 12.2 实现

| 交付 | 文件 / 对象 | 要点 |
|---|---|---|
| 设备模拟器 | `adapters/mqtt_adapter/sim_esp32_greenhouse.py` | 设备 id `irrigation_01`；发布 UniSpec(retain) 即被自动发现；周期上报土壤湿度 / 光照 / 水泵状态；订阅命令 topic，`control_pump` 写命令以 QoS1 回执（带 `request_id`）；水泵单次时长上限 600s；暴露 3 个工具 `get_soil_moisture` / `get_light_intensity` / `control_pump` |
| 工作流蓝图 | `core/workflow/workflows_hardware.yaml::smart_irrigation` | 3 步：s1 读土壤湿度 → s2 读光照强度 → s3 条件开泵（`{{s1.output}} < 30`，`duration: 300`） |
| 单元测试 | `tests/unit/test_esp32_greenhouse_sim.py` | 7 passed（UniSpec 契约 / 读路径 / 无状态 1006 / 写回执 / 工作流定义） |

启动命令：
```
python -m adapters.mqtt_adapter.sim_esp32_greenhouse --broker mqtt://127.0.0.1:1883 --init-soil 25
```

### 12.3 实测结果（模拟器）

| 指标 | 真机（原记录，未实测） | 模拟器（本次实测） |
|---|---|---|
| 自动发现（上电 → tools/list 可见） | 8.6s | **0.23s** |
| 浇水闭环总耗时（3 次） | 2.8s | **1.30s**（1.29 / 1.29 / 1.30s） |
| 水泵写回执 | 212ms | **100ms** |
| 传感器读取 | 0ms（缓存） | **0ms**（缓存） |

- 判据：`smart_irrigation` 三步全 ok；s3 返回 `pump=on` 且 `request_id` 等于本次命令 trace_id（写回执成立）；
  开泵后土壤湿度由 22.4% 回升至 34.4%，复现"浇水后读数爬升"的物理行为；
- 全量测试：`pytest` **179 passed, 5 skipped**（跳过为 fastmcp / cryptography 可选依赖，与本次改造无关）；
- 证据：`docs/evidence/esp32_simulator_e2e_20261004.txt`。

### 12.4 遗留

- 真机固件为**后续可选轨**：`docs/hardware/firmware/esp32/` 骨架保留，未烧录、未实测；
- 本节改动未提交 git（等用户确认后一并提交）。

---

## 十三、全面检查与 P0/P1 修复批次（2026-10-04）

### 13.1 口径全面实测（结论，唯一来源 `docs/口径速查表.md`）

- **工具**：全量 **22 个** = 软件档 11 + 硬件档 8（4 类真实硬件）+ 温室模拟节点 3；
  日常演示档 **14 个**（软件档 11 + 温室模拟节点 3），档位隔离；
- **测试**：`python -m pytest -q` → **203 项全部通过、0 跳过**（fastmcp 4.0.10 / cryptography 50.0.2
  本机可选依赖安装后全绿）；
- **适配器**：已实装 **5 类**（MQTT / CLI / REST / 脚本 / 数据库）+ **规划 1 类**（WebSocket）；
- **硬件**：4 类真实硬件 + 1 类模拟节点（ESP32 温室 SIL）。
  （"真机 → 模拟器"决策及实测 0.23s / 1.30s / 100ms 见第十二章，此处不复述。）

### 13.2 安全修复（P0/P1）

| 项 | 说明 |
|---|---|
| Bearer Token 鉴权 | 网关默认监听 127.0.0.1；设 `HUB_API_TOKEN` 后 `/mcp` 与 `/workflows/recent` 需 `Authorization: Bearer`（401=未授权，JSON-RPC 错误码 -32001） |
| 权限服务端裁决 | 鉴权开启时权限由服务端裁决：认证=admin、未认证=read；客户端 `permission_level` 仅作提示 |
| 限流 key 服务端派生 | 限流桶 key 由服务端按认证身份派生，不信任客户端自报 caller |
| SSRF 增强 | 域名先 DNS 解析校验 + 非常用端口拒绝；`HUB_REST_CHECK_DNS=0` 可关 DNS 校验 |
| 审计面板 XSS 转义 | 审计面板全部输出 HTML 转义 |
| SQL 层 caller 筛选 | 审计/工具查询在 SQL 层按 caller 筛选（防拼接/越权） |

### 13.3 模拟器行为测试补齐

- 温室模拟器（`sim_esp32_greenhouse` + `smart_irrigation`）行为测试补齐：浇水闭环 3 次
  （1.29 / 1.29 / 1.30s，均值 1.30s）、写回执 100ms、读缓存 0ms、自动发现 0.23s；
- 证据：`docs/evidence/esp32_simulator_e2e_20261004.txt`；
- 本节改动已随 P0/P1 里程碑提交（git：`0960754` 代码 / `b812e14` 文档与证据 /
  `1b96601` 研究报告移出跟踪）。

---

## 十四、P2 加固批次（2026-10-05）

### 14.1 修复内容

| 项 | 说明 |
|---|---|
| FastMCP Bearer 覆盖 | `--gateway fastmcp` 此前绕过 create_app 的 Bearer 中间件（P0-BE-2 只护自研路径）；现设置 `HUB_API_TOKEN` 后由 FastMCP ASGI 入口的 `BearerTokenMiddleware` 做同样校验（401 + -32001，恒时比较，`/mcp*` 受保护）；前端改经 `internal=True` 受信中继（身份取自 `HUB_FASTMCP_CALLER` / `HUB_FASTMCP_PERMISSION`），鉴权模式下写操作按配置裁决、不降权也不旁路；`MetaTools.execute` 中继同步 internal（目标工具仍完整走 Guard 管道） |
| BE-5 审计自增主键 | audit 表主键由 `trace_id`（客户端可控、可重复，OR REPLACE 会静默覆盖历史记录）改为 `id INTEGER PRIMARY KEY AUTOINCREMENT`；老库打开时自动迁移（记录全量保留、按原插入序重排）；trace_id 降级为索引关联键；`query_audit` 按 id 倒序（同秒记录不再歧义） |
| BE-6 MQTT 重连退避 | `reconnect_delay_set(min=1, max=30)`，公共 broker 网络抖动时避免固定间隔重连风暴 |
| BE-7 REST 连接池 | 每调用一次 `httpx.request` → 复用 `httpx.Client`（timeout / follow_redirects 配置一致）；新增 `on_shutdown` 释放连接池 |
| UI-3 概览 SQL 聚合 | 新增 `store.audit_stats()`（COUNT/SUM/AVG），概览页不再拉 1000 条记录到 Python 计算 |
| UI-4 本地时区 | 审计页时间列由 UTC 原样展示改为转本地时区（解析失败原样截断） |
| UI-5 schema_hash 展示 | 审计页新增 schema_hash 列（前 12 位 + title 属性全量，均 HTML 转义） |
| T-3 依赖分层 | `requirements.txt`（运行时）/ `requirements-dev.txt`（pytest / amqtt / 文档工具） |
| T-4 测试基建 | `pytest.ini`（testpaths / markers）+ GitHub Actions CI（ubuntu / windows × Python 3.12 / 3.14） |
| 子进程解码加固 | CLI / Script 适配器 `subprocess.run` 增加 `errors="replace"`：非 UTF-8 子进程输出不再令 reader 线程抛 UnicodeDecodeError（此前会导致 stderr=None → AttributeError，属环境相关偶发） |

### 14.2 测试与口径

- `python -m pytest` → **216 项全部通过、0 跳过**（较 P0/P1 批次 +13：审计存储 3、
  REST 连接池复用 1、FastMCP Bearer 与受信中继 9）；
- 口径已同步：`docs/口径速查表.md`（测试行 / 作废口径 / 使用约定）、README、api.md（v0.5.1）、
  研究报告（摘要与表 15）、答辩讲稿、build_ppt.js；
- 材料同步：研究报告 docx 重新导出；申报书 / 查新 / 核对清单中的测试数 203 → 216。
