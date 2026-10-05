# UniAgent Hub 项目改进实施计划

> 依据：`项目改进方案/UniAgent Hub 完整改进规划.txt`（下称"改进规划"）、`项目改进方案/硬件通用性测试方案.txt`
> 日期：2026-10-03 · 状态：**第 1 批已实施并验证**（203 项测试全绿 · 新模块覆盖率 91%）
> 范围约束：研究报告类文档（docs/研究报告.*）的修改**推迟到硬件测试完成后**，本批次未修改。

## 1. 可行性探测结论（实施前）

| 探测项 | 结论 | 依据 |
|---|---|---|
| FastMCP 4 可安装性 | ✅ PyPI 4.0.10；依赖**纯增量**（不降级现有锁定版本），实测可 import | `pip index versions fastmcp` / `pip install --dry-run` |
| cryptography / PyJWT | ✅ 随 fastmcp 安装（50.0.2 / 2.15.1）→ Ed25519 签名可行 | 安装输出 |
| Python 3.14 兼容 | ✅ 216 项测试在装完新依赖后全绿 | pytest |
| 自研网关回退 | ✅ 保留为默认主路径；FastMCP 为**可选前端**（`--gateway fastmcp`） | 架构未破坏 |
| 前端（React 19 + Tauri 2） | ⏸ 需 Node/Rust 工具链与多平台构建，本机未就绪 → 后续批次 | 见 §4 批 3/4 |
| ESP32 固件 | ⏸ 需 PlatformIO + 硬件器件 → 硬件测试阶段后实施 | 见 §4 批 5 |
| 本机硬件现状 | 无 USB 摄像头、无智能插座；有手机（可选）→ 已配 mock 预演链路 | 硬件档实测见 §3 |

## 2. 第 1 批实施明细（已完成）

| # | 改进规划条目 | 落地方式 | 关键文件 | 开关 / 默认 | 验证 |
|---|---|---|---|---|---|
| 1 | §1.1/§2 协议层迁移 FastMCP 4 | **兼容前端**（元工具暴露）：协议层交给 FastMCP（streamable HTTP），执行/安全/审计仍走自研网关；自研网关保留为默认与回退路径 | `core/gateway/fastmcp_server.py`、`main.py --gateway` | `--gateway fastmcp`（环境变量 `HUB_GATEWAY`）；**默认 selfdev** | in-memory Client 集成测试 4 项 + 实测 |
| 2 | §3 渐进式工具发现（4 元工具） | 自研实现 `discover_tools / get_tool_schema / execute_tool / refresh_registry`；execute_tool 透传完整 Guard 管道（1001/1002/1003/1004/1007 语义一致）+ 递归防护 + 元层审计 | `core/gateway/meta_tools.py`、`core/gateway/server.py` | `--meta-tools` / `HUB_META_TOOLS=1`；**默认关闭**（全量列表，演示链路不受影响） | 单元测试 14 项 + FastMCP 前端实测 |
| 3 | §4 适配器生命周期 + entry_points | 5 个适配器新增 `on_startup / on_health_check / on_shutdown`；`/healthz` 汇总各适配器健康状态；`uniagent_hub.adapters` 组 entry_points 自动加载第三方适配器（失败不阻断启动） | `core/adapters/plugins.py`、各适配器、`main.py`、`server.py` | 插件自动加载（`--no-plugins` 关闭） | 单元测试 4 项 + healthz 实测（8 个适配器实例） |
| 4 | §5.1 工具投毒防护（Schema 签名） | 工具定义 SHA-256 内容哈希（name/description/inputSchema 规范化 JSON）；Ed25519 对 `{tool, schema_hash, version}` 签名；审计记录携带 `schema_hash`；新增 `server/attestation` RPC | `core/guard/attestation.py`、`audit.py`、`server.py` | 哈希默认开启；**签名需设 `HUB_ATTESTATION_KEY`**（PEM 路径） | 单元测试 6 项 + RPC 实测（11 哈希） |
| 5 | §5.3 审计防篡改（哈希链） | `rec_hash = sha256(pre_hash + 记录内容)` 逐条链接；`verify_chain` 校验（篡改定位到条）；跨进程重启自动接续；SQLite 增量列迁移 | `core/guard/audit.py`、`core/registry/store.py` | `HUB_AUDIT_CHAIN=1`；**默认关闭** | 单元测试 6 项（含篡改检出） |
| 6 | 硬件测试配套（§7 + 硬件方案） | 4 个硬件测试的脚本/配置/mock/调试工具（见 `docs/hardware/`）；REST 适配器补齐 **JSON body 发送**与 body_* 参数注册（修复历史缺陷）；设备类 Spec 禁用只读缓存（写后读一致） | `adapters/**`、`scripts/mock_plug_api.py`、`scripts/mock_phone_sensor.py`、`scripts/hardware_probe.py`、`core/workflow/workflows_hardware.yaml` | `HUB_CLI_CONFIGS / HUB_SCRIPT_CONFIGS / HUB_REST_SPECS / HUB_WORKFLOWS` 分号分隔多份配置 | 硬件档端到端实测（§3） |
| 7 | §11 版本锁定（部分） | requirements 新增 fastmcp/cryptography/PyJWT/pytest-cov（锁版本） | `requirements.txt` | — | 安装 + 全量回归 |

> 未纳入本批（列入 §4 路线图）：React 19 前端、Tauri 2 桌面封装、SQLAlchemy/WebSocket 适配器、Tuya 签名认证插件、JWT 令牌中间件、Prometheus/Grafana/OpenTelemetry、CI/CD 与治理文件、72h 长稳。

## 3. 验证记录（2026-10-03）

- **测试**：`pytest -q` → **175 passed**（第 1 批新增 35 项：Meta-Tools 14 / 插件 4 / 签名 6 / 哈希链 6 / FastMCP 前端 4 / REST body 1；复查批次 +1 混合文件链校验）
- **覆盖率**（pytest-cov）：新增模块 **91%**（plugins 93% / meta_tools 93% / attestation 93% / audit 91% / store 87%）；
  整体 70%（缺口主要为历史模块 `agent/llm_agent.py` 等，见批 2.5）
- **硬件档端到端实测**（本地 broker + mock 插座 + 手机模拟器 + 温度模拟器）：
  - 19 工具注册（默认 11 + 系统监控 2 + 插座 2 + 摄像头 2 + 手机 2）、6 个工作流（含 4 个硬件工作流）
  - `get_system_cpu=20~30`、`get_system_memory≈17.7GB`、`plug_set_power` 写后读一致、`get_phone_battery≈70`
  - 闭环验证：`office_auto_light`（15°C < 20 → 自动开插座 → 插座状态 power=true）
  - `security_monitor` 在无 opencv 时按预期降级（结构化错误 → 条件为假 → 抓拍步骤跳过）
  - `hardware_probe check`（8 个预期工具全在 + 5 个只读探测全 ✓）、`watch`（收到 phone_01/temp_01 注册）、`call --permission write` 通过
- **档位隔离修复**：联调中发现硬件档注册记录会持久化进演示库（默认档启动时从 SQLite
  恢复出 6 个无适配器的孤立工具，19 而非 11）→ 新增 `HUB_DB` 档位隔离（硬件档用
  `data/uniagent_hardware.db`），并已清理演示库（恢复 11 工具，实测确认）
- **无外部硬件用例已全部执行（2026-10-03）**：20/20 通过、0 失败（TC-2x/3x/4x + TG-1~4 +
  摄像头安全/降级用例）；插座/手机为 mock 预演，PC 系统监控为全真实测。
  记录与证据：`docs/hardware/records/20261003_hardware_test.md`、
  `docs/evidence/hardware_test_20261003.txt`；剩余待人工：摄像头取景 TC-11/12/13 与真机复测
  （复现命令见记录 §7/§8）。执行期新修 2 项：`HUB_AUDIT_FILE` 审计档位隔离、
  哈希链混合文件校验兼容（均含单测，pytest 175 全绿）
- **复查修复批次（2026-10-04）**：A1 哈希链**分段校验**（链段→关链→再启链 不误报；篡改全局下标定位）；
  A2 元工具审计 schema_hash 回退到元工具定义 + `hardware_test_run.tg3` 按工具名分组（顺序无关）；
  A4/B3 FastMCP 前端 transport 改 **streamable-http**，实测协商 2026-07-28（证据
  `docs/evidence/fastmcp_http_smoke_20261004.txt`）；B1/B2/A3 文档统一（175 测试 / opencv 5.0.0 /
  REST 连接池列入批 5）；pytest **180 passed**
- **回退演练**：默认 `python main.py` 行为与 v1.3 演示档完全一致（11 工具；139→175 测试不改变默认语义）

## 4. 后续路线图（任务分解 / 优先级 / 时间节点 / 资源）

| 批次 | 优先级 | 任务 | 依赖 / 前置 | 预计 | 交付物 |
|---|---|---|---|---|---|
| **批 2** | P0 | **硬件测试执行**（人工）：按 `docs/hardware/hardware_test_plan.md` 接线并跑 4 个测试，用模板记录 | 采购硬件（§资源表）、安装 opencv | 1-2 天 | 硬件测试记录 + 证据（截图/日志/审计导出） |
| **批 2.5** | P1 | 历史模块测试补齐（llm_agent 解析/降级链、MQTT 写路径），整体覆盖率 → >80% | 无 | 2-3 天 | 覆盖率报告 |
| **批 3** | P1 | React 19 SPA + Ant Design + React Flow 12 + ELKjs（工具注册中心/工作流编排器/安全中心/审计/监控 6 页） | Node 工具链；后端 API 已就绪（`/mcp` + `/workflows/recent` + `/healthz`） | 2 周 | 可交互管理界面 |
| **批 4** | P2 | Tauri 2 桌面封装（externalBin sidecar + 三平台 target-triple + GitHub Actions 矩阵） | Rust 1.80+；批 3 | 1 周 | 桌面安装包 |
| **批 5** | P2 | 适配器扩容：SQLAlchemy SQL 适配器、WebSocket 适配器；**Tuya 签名认证插件**（HMAC-SHA256 token 流）；JWT 短期令牌中间件；**REST 适配器共享客户端/连接池**（httpx.Client 复用，降低冷调用延迟，配对应单测） | 无（可并行） | 2 周 | 6 类适配器全覆盖 + 认证增强 |
| **批 6** | P2 | 开源协作：ruff + mypy + pip-audit + CodeQL CI；CONTRIBUTING / SECURITY / LICENSE(Apache-2.0) | Git 远端；LICENSE 版权署名需人工确定 | 1 周 | CI 流水线 + 治理文件 |
| **批 7** | P3 | 长稳（72h）+ 性能基准（P95<5s）+ Prometheus/Grafana + OpenTelemetry（可选） | 部署环境（Docker 引擎修复或云主机） | 1-2 周 | 稳定性/性能报告 |
| **批 8** | P3 | ESP32-S3 温室节点固件（PlatformIO + ArduinoJson + PubSubClient）与 HIL 测试 | 硬件到货（ESP32-S3 + DHT22/BH1750/土壤湿度/继电器水泵） | 2 周 | 固件 + HIL 报告 |

### 资源需求

| 类别 | 明细 | 说明 |
|---|---|---|
| 硬件（硬件测试） | USB 摄像头（已有/约 50 元）、智能插座或本地继电器（约 30-80 元）、Android 手机（已有） | 合计约 80-130 元（不含手机），见 `docs/hardware/hardware_test_plan.md` |
| 硬件（批 8，可选） | ESP32-S3 + 温湿度/光照/土壤湿度/继电器水泵套件 | 约 100-200 元 |
| 软件 | opencv-python（测试 1 用，按需安装）；Node.js 20+（批 3）；Rust 1.80+（批 4）；PlatformIO（批 8） | 均已写明安装方式 |
| 人工 | 硬件接线与实测、录屏讲解、LICENSE 署名、比赛材料提交 | 依据 TRAE 规则，涉硬件/桌面操作一律人工执行 |

## 5. 风险与回退

| 风险 | 影响 | 回退 / 缓解 |
|---|---|---|
| FastMCP 4 与自研语义偏差（协议细节） | 前端表现不一致 | 默认仍是自研网关；`--gateway selfdev` 一键回退；集成测试锁定 4 项关键语义 |
| 元工具模式影响既有客户端 | Agent 只看到 4 个元工具 | 默认关闭；开启时 `discover_tools` 提供完整目录导航 |
| 签名/哈希链引入开销或格式变化 | 审计体积增大 | 哈希链默认关闭；`schema_hash` 为附加字段（旧记录兼容，SQLite 自动迁移） |
| 硬件到货延迟 | 批 2 阻塞 | mock 预演链路已就绪（`mock_plug_api` / `mock_phone_sensor` / 温度模拟器），测试流程可先跑通 |
| 依赖升级破坏演示 | 演示失败 | 版本锁定 + 已验证"纯增量"；`requirements.txt` 新增项均可选未启用 |

## 6. 附：新增开关速查

```powershell
# 元工具渐进式发现（4 元工具）
python main.py --meta-tools
# FastMCP 4 协议前端（自研网关为回退）
python main.py --gateway fastmcp
# 审计哈希链（防篡改）
$env:HUB_AUDIT_CHAIN = "1"
# 工具清单 Ed25519 签名（先生成密钥：见 scripts/attestation.py genkey）
$env:HUB_ATTESTATION_KEY = "data/attestation_key.pem"
# 硬件测试档（4 个测试的配置与工作流；详见 docs/hardware/）
$env:HUB_DB = "data/uniagent_hardware.db"   # 档位隔离：测试数据写入独立库，不污染演示库
$env:HUB_AUDIT_FILE = "data/audit_hardware.jsonl"   # 审计 JSONL 一并隔离
$env:HUB_CLI_CONFIGS = "adapters/cli_adapter/configs/cli_tools.yaml;adapters/cli_adapter/configs/system_monitor.yaml"
$env:HUB_SCRIPT_CONFIGS = "adapters/script_adapter/configs/scripts.yaml;adapters/script_adapter/configs/hardware_tests.yaml"
$env:HUB_REST_SPECS = "adapters/rest_adapter/specs/open_meteo.yaml;adapters/rest_adapter/specs/smart_plug.yaml"
$env:HUB_REST_ALLOWED_PRIVATE_HOSTS = "127.0.0.1"
$env:HUB_WORKFLOWS = "core/workflow/workflows_hardware.yaml"
```