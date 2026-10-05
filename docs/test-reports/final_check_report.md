# UniAgent Hub 最终检查报告

> 检查日期：2026-09-26 · 检查范围：全部文档 / 代码 / 依赖 / 全栈试运行 / 性能 / 安全
> 结论：**平台核心功能全部可用（119 测试全绿，试运行拦截率 100%），但发现 2 项高优先级、6 项中优先级、8 项低优先级问题**，按约定先提交错误报告待人工确认后再修复。

---

## 第一部分：结构化错误报告（待人工审查确认）

严重程度定义：🔴 高 = 影响比赛交付/演示；🟡 中 = 影响功能正确性/文档可信度；🟢 低 = 细节完善。

### ERR-01 🔴 git 仓库零提交，版本管理缺失
- **类型**：流程缺陷
- **位置**：仓库根 `.git/`（main 分支无任何 commit，全部文件 `??` 未跟踪）
- **影响**：比赛材料要求附"Git 提交记录"作为工作量证据；当前无版本基线、无法回溯、答辩无法展示开发轨迹
- **初步分析**：开发期间从未提交。建议按阶段分批提交（阶段 0 文档 → 阶段 1 → 2 → 3），提交信息引用 dev_log
- **处置建议**：需人工确认提交策略（一次性 vs 按阶段拆分）

### ERR-02 🔴 Docker Compose 引用不存在的 Dockerfile，README 快速开始命令不可用
- **类型**：部署缺陷 + 文档不一致
- **位置**：[deploy/docker-compose.yml](deploy/docker-compose.yml) L26/L45 引用 `deploy/Dockerfile.hub`、`deploy/Dockerfile.agent`（文件不存在）；[README.md](README.md) L36 "快速开始"仅给出 docker compose 命令
- **影响**：`docker compose up -d` 只能启动 emqx，hub/agent 构建失败；评委按 README 操作会失败
- **初步分析**：本机 Docker 引擎 500 导致容器化验证被搁置，Dockerfile 一直未补
- **处置建议**：补两个 Dockerfile + README 双路径（Python 直跑为主、Docker 为可选），或 README 暂时改为仅 Python 启动

### ERR-03 🟡 get_ac_state 只读能力被资源级 write 权限覆盖
- **类型**：功能缺陷（权限粒度）
- **位置**：[adapters/mqtt_adapter/sim_ac.py](adapters/mqtt_adapter/sim_ac.py) UNISPEC（constraints.permissionLevel=write）× [core/gateway/server.py](core/gateway/server.py) 权限校验（仅看 spec 级）
- **现象**：试运行中 `get_ac_state`（readOnly=true 的能力）以 read 权限调用返回 1003
- **初步分析**：Gateway 权限校验只看 `spec.constraints.permissionLevel`，未结合 `capability.readOnly` 下调需求；导致"查询空调状态"也要求 write 权限，违反最小权限原则
- **处置建议**：readOnly 能力 → 要求 read；写能力 → 要求 spec 声明级别。需补单测（契约测试）

### ERR-04 🟡 api.md `server/discover` 响应结构与实现不一致
- **类型**：文档不一致（冻结契约漂移）
- **位置**：[docs/api.md](docs/api.md) §2.3 写 `"protocolVersions": [...]`；实现返回 `protocolVersion + supportedVersions + capabilities.workflows`
- **处置建议**：更新 api.md 至 v0.2 并注明变更记录（冻结条款要求）

### ERR-05 🟡 api.md `run_workflow` 契约与实现不一致（重大设计演变未同步）
- **类型**：文档不一致
- **位置**：[docs/api.md](docs/api.md) §2.4 定义 Agent 动态传入 `steps` 蓝图；实现为预定义蓝图（YAML 注册）+ `workflow` 名称 + `params` 参数
- **初步分析**：演变为预定义注册是**安全加固**（不接受 Agent 动态编排任意工具序列），但文档未记录此决策及理由——答辩被对照文档追问时会失分
- **处置建议**：更新 api.md §2.4，写明"动态蓝图 → 预定义蓝图的演变及安全理由"

### ERR-06 🟡 unispec.md 示例违反自身 Schema + 扩展字段未收录
- **类型**：文档准确性
- **位置**：[docs/unispec.md](docs/unispec.md) §6.3 示例 `"rateLimit": "10/min"`（合法格式为 `10/m`，自家 §9 pattern 不匹配——阶段 2 代码已踩过同一坑）；§4/§9 未收录已实现的 `paramPatterns`、`stateField` 扩展字段（冻结条款要求升版本号）；§8 注册 topic 表述 `uniagent/register` 与实现 `uniagent/register/<device_id>` 不符，且"tools/list 变更广播""status 心跳"未实现（超前承诺）
- **处置建议**：unispec.md 升级 v0.1.1，补扩展字段与 CHANGELOG，删除未实现承诺或标注"规划中"

### ERR-07 🟡 README.md 严重滞后
- **类型**：文档不一致
- **位置**：[README.md](README.md) 状态停留在"阶段 0 已完成"；仓库结构缺 `scripts/ generated_cli/ data/ docs/design 等`；未提 Python 启动方式（当前唯一可用的方式）
- **处置建议**：更新为阶段 3 完成状态 + Python 启动主路径

### ERR-08 🟡 Guard 管道顺序：限流先于参数校验
- **类型**：设计权衡（需人工决策，非 bug）
- **位置**：[core/gateway/server.py](core/gateway/server.py) Guard 顺序 = 权限 → 限流 → 参数校验
- **现象**：试运行中 REST 工具超限后，携带恶意参数的请求返回 1004 而非 1002（该用例标记 FAIL；实际恶意请求仍被拦截，拦截率 100%）
- **初步分析**：限流前置利于防 DoS（当前顺序有合理性）；代价是超限期间 block_reason 只记限流，不体现参数恶意性（args 已完整入审计，可事后分析）。另一面：测试用例自身先做了 11 次调用撞限额，属测试设计问题
- **处置建议**：二选一——维持现状（答辩说明权衡）或调整为"参数校验 → 权限 → 限流"（恶意请求优先暴露细节）。需人工确认

### ERR-09 🟢 依赖未锁版本
- **位置**：requirements.txt 全部为 `>=` 约束。复现性风险（评委环境安装新版本可能不兼容）
- **处置建议**：生成精确版本清单（实测：fastapi 0.141.1 / uvicorn 0.54.0 / pydantic 2.13.5 / PyYAML 6.0.3 / paho-mqtt 2.1.0 / httpx 0.28.1 / pytest 9.1.1）

### ERR-10 🟢 PRD/architecture 细节偏差
- PRD §4 写天气用 OpenWeather，实际 open-meteo；architecture §3/§6/§7 声称 MCP SDK/FastMCP/structlog，实际自研 JSON-RPC 网关与轻量日志（合理简化但未同步）；api.md 声称 stdio 传输，实际仅 HTTP

### ERR-11 🟢 演示稳定性风险（非缺陷）
- 模拟器温度波动 ±0.6：试运行时 init-temp=30 漂到 27.6 < 28，工作流 s3 正确 skipped——条件分支无误，但现场演示可能"空调没开"。
- 建议：演示前 `--init-temp 31`（漂移后仍 >28）或阈值降为 27；get_weather 演示前预热一次（冷调用约 2.4s）

### ERR-12 🟢 generated_cli/ 入库策略未定
- 生成物目录未加入 .gitignore 且未提交。建议：作为"CLI 反向生成"成果保留入库（或注明可由脚本再生）

---

## 第二部分：文档审查结果

| 文档 | 完整性 | 准确性 | 一致性 |
|---|---|---|---|
| prd.md | ✅ | ⚠️ ERR-10 | ✅ |
| unispec.md | ⚠️ 扩展字段缺收录 ERR-06 | ⚠️ 示例非法 ERR-06 | ⚠️ |
| api.md | ✅ | ❌ ERR-04/05 契约漂移 | ❌ |
| architecture.md | ✅ | ⚠️ ERR-10 | ⚠️ |
| roadmap.md | ✅ 阶段 0-3 状态准确 | ✅ | ✅ |
| dev_log.md | ✅ 覆盖 0-3，24 项工程问题 | ✅ 与 evidence 抽查相符 | ✅ |
| design/ phase2+3 | ✅ | ✅ | ✅ |
| test-reports/ ×2 | ✅ | ✅ 数据与 evidence 一致 | ✅ |
| evidence/ ×2 | ✅ E1-E6 原始输出 | ✅ | ✅ |
| README.md | ❌ 滞后阶段 0 ERR-07 | ❌ 快速开始不可用 ERR-02 | ❌ |
| 方案 txt / 开发路线 txt | ✅ | ⚠️ 与实现偏差见第三部分 | — |

**结论**：阶段过程类文档（dev_log/design/test-reports/evidence）质量高、证据链完整；冻结契约类文档（api/unispec）与实现发生漂移，README 需重写。

## 第三部分：技术栈评估

**依赖兼容性**：7 项依赖全部满足 requirements 约束，无冲突；Python 3.14.3（paho WMI 挂起已用兼容桩规避，3 处内聚处理）。

**方案 vs 实现偏差分类**（合理简化，建议在研究报告"技术选型说明"中主动交代）：

| 方案声明 | 实际实现 | 评价 |
|---|---|---|
| FastMCP 4 + 官方 SDK | 自研 FastAPI + JSON-RPC 2.0 网关（~250 行） | ✅ 合理：MCP 核心仅 5 个方法，自研便于 Guard 横切与答辩讲解 |
| Python + TypeScript 双语言 | 纯 Python | ✅ 合理：单人比赛项目降低复杂度 |
| PraisonAI/OpenClaw Agent | 脚本式 Demo Agent（无 LLM 实接） | ⚠️ 需说明：当前"Agent"是 MCP 客户端演示脚本；接入真实 LLM 属阶段 4 增强项 |
| structlog/Prometheus | print + audit + Dashboard | ✅ 可接受（Prometheus 原定可选） |
| stdio + HTTP 双传输 | 仅 HTTP | ⚠️ 文档声称与实现不符（ERR-10） |
| EMQX（Docker） | 公共 broker emqx.io + compose 待验证 | ⚠️ ERR-02 |

## 第四部分：功能试运行记录（2026-09-26）

环境：Windows · Python 3.14.3（.venv）· 公共 MQTT broker · open-meteo

| 检查项 | 结果 |
|---|---|
| tools/list | ✅ 9 工具（CLI×2 + IoT×4 + REST×1 + Script×1 + run_workflow） |
| CLI 调用 git_status | ✅ 65ms，真实 git 输出 |
| IoT 读 温度/湿度 | ✅ 27.6°C / 60.9%（MQTT 缓存） |
| IoT 读 get_ac_state | ❌ 1003（ERR-03 权限粒度） |
| REST get_weather | ✅ 2378ms（冷）返回北京天气 JSON |
| Script file_summary | ✅ 70ms 返回 {count:17, files:[...]} |
| run_workflow(office_cooling) | ✅ ok，步骤 [ok, ok, skipped]（s3 skipped 为条件正确行为：温度 27.6<28，见 ERR-11） |
| Dashboard / /audit /workflows | ✅ 3 页 HTTP 200 |
| 持久化重启恢复 | ✅ 重启后 9 工具完整恢复；SQLite 6 资源、审计 63 条可查 |

## 第五部分：性能测试数据

| 指标 | 采样（n=10） | 达标（<500ms） |
|---|---|---|
| git_status（CLI） | avg 68ms / p95 69ms / max 70ms | ✅ |
| get_temperature（IoT 缓存） | 0ms | ✅ |
| file_summary（脚本） | avg 70ms / p95 73ms / max 76ms | ✅ |
| get_weather（REST，缓存命中后） | p50 0ms（首次冷调用 2137-2378ms） | ✅（缓存兜底，演示需预热） |
| SQLite audit 查询 100 条 | 5.4ms | ✅（<10ms） |
| run_workflow（3 步，含 REST 冷） | ~4s（阶段 3 实测 3969ms） | 一次性编排，不适用单工具标准 |

## 第六部分：安全验证

| 用例 | 期望 | 实际 | 结果 |
|---|---|---|---|
| CLI 注入 `; rm -rf` | 1007 | 1007 | PASS |
| REST 未知参数 | 1002 | 1004* | 拦截✅（错误码差异见 ERR-08） |
| Script 未知参数 | 1002 | 1002 | PASS |
| 越权调 ac_control（read） | 1003 | 1003 | PASS |
| 越权调 run_workflow（read） | 1003 | 1003 | PASS |
| action enum 越界 | 1002 | 1002 | PASS |
| temperature 范围越界（99） | 1002 | 1002 | PASS |
| 不存在工具 | 1001 | 1001 | PASS |
| 限流（ac_control 5/m） | 1004 | 第 6 次 1004 | PASS |
| SSRF 私网地址 | 拦截 | 单测覆盖（127.0.0.1/192.168.*） | PASS |
| 表达式注入（8 类） | 拒绝 | 单测覆盖 ExprError | PASS |
| 工作流递归 | 拒绝 | 注册期拒绝（单测） | PASS |

**恶意请求拦截率 100%**（全部被拦截，仅 1 例错误码归类与预期不同）。审计记录完整：近 500 条中 blocked 20 条，含 args/trace_id/guard_result。

## 第七部分：改进建议（按优先级）

**必须处理（赛前）**
1. ERR-01 git 按阶段提交，建立版本基线
2. ERR-02 补 Dockerfile + 重写 README（Python 直跑为主路径）
3. ERR-03 权限粒度修复（readOnly 能力降为 read 要求）+ 契约测试补充
4. ERR-04/05/06/07 契约文档同步（api.md v0.2、unispec.md v0.1.1、README）
5. ERR-11 演示参数固化（init-temp 31 / 预热天气）

**建议处理**
6. ERR-08 Guard 顺序决策（维持现状并文档化权衡，或调整）
7. ERR-09 依赖锁版本
8. LLM Agent 接入（哪怕最小：DeepSeek API 单轮 function-calling 演示，增强"Agent 层"说服力）

---

*本报告由自动化检查生成，所有错误项（ERR-01 ~ ERR-12）待人工审查确认后按优先级处置。原始数据：data/final_check_result.log、data/final_check_restart.log*
