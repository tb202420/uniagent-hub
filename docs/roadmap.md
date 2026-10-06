# UniAgent Hub — 研发路线图与任务看板

> 版本：v0.3 · 更新：2026-10-04 · 状态：阶段 0-3 已完成 + 改进方案第 1 批与安全批次已落地；阶段 4 主体交付（演示 / 文档 / 研究报告 / 答辩 PPT，2026-10-04 口径核定版），Docker Compose 实测与材料提交为赛前收尾

## 0. 总原则

1. **规范先行**：`UniSpec`（v0.1 冻结 → v0.2.0 扩展）所有模块围绕它开发；
2. **垂直切片优先**：先打通"Agent → Gateway → CLI 适配器 → 真实命令"最小闭环；
3. **先易后难**：CLI → MQTT 模拟器 → REST；
4. **安全内建**：参数校验 / 注入防护 / 权限 / 审计从 MVP 第一行代码开始；
5. **演示驱动**：所有开发围绕"智能办公环境管理"5 分钟演示收敛。

## 1. 阶段看板

### 阶段 0 — 需求冻结与架构定稿（✅ 已完成 2026-09-25）

| 任务 | 状态 | 交付物 |
|---|---|---|
| 明确比赛评分点映射 | ✅ | [docs/prd.md](prd.md) §5 |
| 冻结 UniSpec v0.1 | ✅ | [docs/unispec.md](unispec.md) |
| 定义 Gateway 三接口 | ✅ | [docs/api.md](api.md) §2 |
| 定义适配器统一接口 | ✅ | [docs/api.md](api.md) §3 |
| 确定演示场景 | ✅ | 智能办公环境管理（含降级方案） |
| 建仓库与看板 | ✅ | 本仓库 + 本文件 |

**验收**：✅ 各模块接口冻结；✅ 数据流 `Agent → Gateway → Guard → Adapter → 资源` 已画清。

---

### 阶段 1 — MVP 垂直链路（第 1–2 周）

| # | 任务 | 优先级 | 状态 |
|---|---|---|---|
| 1.1 | UniSpec Pydantic 模型 + jsonschema 校验 | P0 | ✅ |
| 1.2 | 内存版 ToolRegistry（注册/查询/删除） | P0 | ✅ |
| 1.3 | CLI 适配器：YAML 注册解析 + `{placeholder}` Schema 生成 | P0 | ✅ |
| 1.4 | CLI 适配器：`subprocess(argv, shell=False)` + 超时 | P0 | ✅ |
| 1.5 | MCP Gateway：`tools/list` + `tools/call`（路由到 CLI） | P0 | ✅ |
| 1.6 | Demo Agent：MCP Client 调用 `git_status` / `file_search` | P0 | ✅ |
| 1.7 | Guard v1 最小集：参数 Schema 校验 + 审计日志 | P0 | ✅ |
| 1.8 | MQTT 模拟器（Python 发温度）+ MQTT 适配器 `get_temperature` | P1 | ✅ 公共 broker E2E 通过 |

**阶段 1 实测结果（2026-09-25）**：
- 47 个单元/集成测试通过（UniSpec / 模板解析 / Guard 注入防护 / Registry / Gateway / MQTT Mock）；
- CLI E2E：Agent → HTTP Gateway → CLI 适配器 → 真实 `git status` 成功，93ms；
- MQTT E2E（公共 broker `broker.emqx.io` + 模拟设备）：设备自动发现 → `tools/list` 4 工具（2 CLI + 2 IoT）→ `get_temperature` 24.9°C / `get_humidity` 56.0%；
- 安全横切验证：CLI 注入 `; rm -rf` → 1007 拦截；MQTT 未知参数 → 1002 拦截；审计落盘 `data/audit.jsonl`；
- 说明：`file_search`（find）需 Linux/Docker；真实 broker E2E 已用公共 broker 完成，EMQX（Docker）待比赛部署环境验证；
- 完整开发记录见 [docs/dev_log.md](dev_log.md)（含 12 项工程问题与解决，可作研究报告"实验过程"附件）。

**验收**：
- [x] Agent 不知背后是 CLI 还是 MQTT，MCP 调用成功（CLI 已验证）；
- [x] `; rm -rf` 类参数被拦截；
- [x] 每次调用有 trace_id 审计记录。

---

### 阶段 2 — 核心模块与多类型适配（第 3–5 周）

| # | 任务 | 优先级 | 状态 |
|---|---|---|---|
| 2.1 | ToolRegistry SQLite 持久化（UniSpec / 权限 / 日志） | P0 | ✅ WAL + 双写 + 重启恢复 |
| 2.2 | 设备自动发现：订阅 `uniagent/register` + 状态 topic | P0 | ✅ 阶段 1 完成，retain 消息保证不丢失 |
| 2.3 | REST 适配器：OpenAPI Spec 导入 → MCP Tool | P1 | ✅ open-meteo get_weather 真实调用成功 |
| 2.4 | 本地脚本适配器 | P1 | ✅ file_summary 115ms，路径白名单 |
| 2.5 | Gateway 多工具路由 + 多服务器聚合（Mediator） | P0 | ✅ 多工具路由；聚合留阶段 3 |
| 2.6 | `server/discover` + 协议版本协商 | P1 | ✅ protocolVersion + supportedVersions |
| 2.7 | Guard v1 完整：readOnly/write/admin 权限 + 限流 | P0 | ✅ 越权 1003 拦截；限流留阶段 3 |
| 2.8 | 注册 ≥5 个工具（2 IoT + 2 CLI + 1 REST + 1 脚本） | P0 | ✅ 6 工具统一注册 |

**阶段 2 实测结果（2026-09-25）**：
- 79 个测试通过（含契约测试：4 类适配器统一拦截未知参数/注入/越权/审计必写）；
- E2E：tools/list 6 工具（2 CLI + 2 IoT + 1 REST + 1 脚本）；get_weather 真实调用 open-meteo；file_summary 115ms；
- 持久化：SQLite tools 5 资源（含自动发现 IoT）+ audit 可查询；Hub 重启后工具完整恢复；
- 安全：SSRF 拦私有地址；API Key env 脱敏；>1MB 响应截断；脚本 `../` 逃逸拒绝；
- 存档：设计方案 docs/design/phase2_design.md、测试报告 docs/test-reports/phase2_test_report.md、过程证据 docs/evidence/phase2_e2e_results.md。

**验收**：
- [x] Agent 通过同一 MCP 接口调用所有类型工具；
- [x] 恶意参数如 `; rm -rf` 被拦截（1007）；
- [x] 审计日志可查询（SQLite + JSONL）。

---

### 阶段 3 — 工作流编排与安全增强（第 6–7 周）

| # | 任务 | 优先级 | 状态 |
|---|---|---|---|
| 3.1 | WorkflowEngine：JSON 蓝图 + 拓扑排序 + `{{s1.output}}` 管道 | P0 | ✅ 3 步闭环 E2E（29.9°C→天气→空调 on/27°C，3.97s） |
| 3.2 | 暴露 `run_workflow` 工具 | P0 | ✅ 内置 MCP 工具（write 级），tools/list 可见 |
| 3.3 | Guard v2：沙箱白名单 + CPU/内存限制 + 注入强校验 | P1 | ✅ 限流（1004）+ scope 隔离 + 失败传播；沙箱沿用 shell=False+白名单 |
| 3.4 | CLI 反向生成：MCP Tool → 可执行 CLI 脚本 | P1 | ✅ 8 个脚本，实跑与 MCP 等价 |
| 3.5 | 可观测性：structlog JSON + 审计 Web 界面 | P1 | ✅ Dashboard 三页（概览/审计/工作流）HTTP 200 |
| 3.6 | 安全测试报告（注入/越权/超时/限流） | P0 | ✅ 119 测试全绿，安全用例见报告 |

**阶段 3 实测结果（2026-09-25）**：
- 9 工具统一注册（含 run_workflow）；一次 `run_workflow(office_cooling)` 完成"测温→天气→开空调"闭环；
- 条件分支（29.9>28 触发）、数据管道（29.9-2=27.9→27）、写操作回执（空调状态确认）；
- 限流 1004（外部桶 5/m 第 6 次拦截）；工作流内步骤 scope 隔离不误伤；递归防护注册期拒绝；
- CLI 反向生成 8 脚本实跑成功；Dashboard 三页 HTTP 200；
- 存档：设计方案 docs/design/phase3_design.md、测试报告 docs/test-reports/phase3_test_report.md、证据 docs/evidence/phase3_e2e_results.md。

**验收**：
- [x] 一次 `run_workflow` 完成"测温 → 判阈值 → 开空调"；
- [x] 注入/越权/超时/限流全部拦截。

---

### 阶段 4 — 演示、文档与答辩（第 8 周）

| # | 任务 | 状态 |
|---|---|---|
| 4.1 | 5 分钟演示脚本（工具列表 → 单工具 → 工作流闭环 → 安全拦截 → CLI 反向生成 → 审计界面） | ✅ docs/demo_script.md（含预热清单与降级方案） |
| 4.2 | 降级方案：MQTT 模拟器 / REST 预热缓存 / 脚本 Agent / 预录视频 | ✅ 已内置于演示脚本 §6 |
| 4.3 | README / 部署指南 / API 文档 / 测试报告 | ✅ README 重写（Python 直跑主路径）+ api.md v0.2 + Dockerfile.hub |
| 4.4 | LLM Agent 接入（可插拔框架） | ✅ agent/llm_agent.py（DeepSeek/百炼/Ollama 可切换，无 Key 脚本降级） |
| 4.5 | 最终检查与修复（12 ERR + 3 SUP） | ✅ 2026-09-26，见 dev_log.md §八 |
| 4.6 | 研究报告 / 查新报告撰写 | ✅ 研究报告已定稿（2026-10-05，216 项测试口径，6 图 17 表）；查新报告 ⬜ |
| 4.7 | 答辩 PPT 与讲稿（USB-C 比喻 + 4 大创新点） | ✅ 已成稿（2026-10-04 口径核定版） |
| 4.8 | Docker Compose 比赛环境实测（本机 Docker 引擎曾 500，需人工修复后验证） | ⬜ |
| 4.9 | 12/1 前提交材料（文件夹命名"所在地市+姓名+UniAgent Hub"、附件≤6MB、查重<5%） | ⬜ |

**验收**：演示连续 3 次无失败；评委听懂"AI 世界的 USB-C"。

---

### 最终检查修复批次（✅ 已完成 2026-09-26）

全面自查发现 12 项问题（ERR-01~12）+ 3 项补充（SUP-01~03），用户逐条评审确认后集中修复：

| 项 | 内容 | 状态 |
|---|---|---|
| ERR-03 | 能力级权限粒度（cap.permissionLevel 优先级公式）+ stateField 推断缺陷 | ✅ 含 4 项回归测试 |
| SUP-03 | MQTT topic 项目前缀 uniagent-hub-rxyc（HUB_TOPIC_PREFIX 可覆盖） | ✅ |
| SUP-01 | LLM Agent 可插拔框架（OpenAI 兼容 + 无 Key 脚本降级） | ✅ |
| ERR-09/02 | 依赖锁版本 + Dockerfile.hub + compose 修正 | ✅ |
| ERR-04/05/06 | api.md v0.2（含变更记录）+ unispec.md v0.2.0 | ✅ |
| ERR-08 | Guard 顺序设计说明写入 architecture.md ADR-3（不改代码） | ✅ |
| ERR-07/11 | README 重写 + demo_script.md（预热/降级/3 轮全绿标准） | ✅ |
| ERR-01/SUP-02 | git 如实分批提交（不伪造时间戳，过程证据以 dev_log/evidence 为主） | ✅ |
| ERR-10/12 | 低优先级细节（gitignore 等赛前收尾） | ⬜ 赛前 |

## 2. 模块依赖关系

```
UniSpec v0.1 (已冻结)
   ↓
ToolRegistry → CLI 适配器 → MCP Gateway → Agent 联调
   ↓
MQTT 适配器 / REST 适配器 / 脚本适配器
   ↓
Guard 安全模块（横切，从阶段 1 开始）
   ↓
WorkflowEngine → CLI 反向生成 + 可观测性 + 演示界面
```

## 3. 风险登记册

| 风险 | 应对 |
|---|---|
| MCP 规范版本变动 | 以官方 SDK 为准，抽象传输层，先 stdio + HTTP |
| ESP32 硬件不稳定 | **已采用模拟器（SIL）**（`sim_esp32_greenhouse`，设备 id `irrigation_01`，已端到端实测 0.23s / 1.30s / 100ms）；真机为后续可选轨（固件骨架已预留于 `docs/hardware/firmware/esp32/`，未烧录、未实测） |
| LLM 输出不稳定 | 演示用固定脚本 + 工具白名单 |
| 沙箱复杂 | 先白名单 + `shell=False`，后资源限制 |
| 时间不足 | 保 MVP + 核心模块，工作流/前端可降级 |
| 答辩讲不清 | USB-C 比喻 + 四大创新点一页纸 |

## 4. 测试策略

| 类型 | 内容 | 验收 |
|---|---|---|
| 单元 | UniSpec 校验 / 模板解析 / 参数校验 | 覆盖率 > 70% |
| 集成 | MQTT/CLI/REST → Gateway | 发现与调用成功 |
| E2E | Agent → 工作流 | 多步一次完成 |
| 安全 | 注入/越权/超时/限流 | 全部拦截并记录 |
| 性能 | 单工具延迟 | < 500ms |
| 演示 | 5 分钟脚本 | 连续 3 次无失败 |
