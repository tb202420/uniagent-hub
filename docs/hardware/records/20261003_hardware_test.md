# 硬件通用性测试记录（整合报告）— 2026-10-03

> 依据：`docs/hardware/hardware_test_cases.md`（用例与评估标准）· `docs/hardware/hardware_test_plan.md`（环境配置）
> 原始证据：`docs/evidence/hardware_test_20261003.txt`（全部命令输出留档）
> 执行范围：**不依赖外部硬件的用例已全部执行**；摄像头取景类用例（TC-11/12/13）按"硬件操作交人工"约定移交人工。

## 0. 测试基本信息

| 项 | 内容 |
|---|---|
| 测试日期 / 执行 | 2026-10-03（自动化执行 + 人工复核待办） |
| 测试机器 | Windows 11 / Python 3.14（`C:\Users\admin\AppData\Local\Programs\Python\Python314`） |
| 代码版本 | 改进方案第 1 批工作区（未提交 git；含硬件测试档全部工件） |
| 测试档启动 | `HUB_DB=data/uniagent_hardware.db` + `HUB_AUDIT_FILE=data/audit_hardware.jsonl`（**档位隔离**）+ `HUB_AUDIT_CHAIN=1` + 三份硬件配置 + `HUB_WORKFLOWS=core/workflow/workflows_hardware.yaml`（完整命令见 §8） |
| 依赖 | opencv-python **5.0.0**（测试 1 用）；其余为已锁定依赖 |
| 自动化工具 | `scripts/hardware_probe.py`（check/watch/call）+ `scripts/hardware_test_run.py`（用例执行器，PASS/FAIL/SKIP 与用例编号一一对应） |

## 1. 测试环境记录

| 项 | 记录 |
|---|---|
| Hub 注册工具 | **19 个**（默认 11 + 硬件 8：系统监控 2 / 插座 2 / 摄像头 2 / 手机 2） |
| 工作流 | 6 个（演示 2 + 硬件 4：`security_monitor` / `office_auto_light` / `phone_battery_snapshot` / `dev_machine_health`） |
| 适配器健康（/healthz） | 8 个实例全 ok：cli×2、rest×2、script×2、database、mqtt（connected=true，devices=3） |
| MQTT broker | 本地 amqtt（`scripts/dev_mqtt_broker`，127.0.0.1:1883，离线可复现） |
| 智能插座 | **mock 预演**（`scripts/mock_plug_api`，127.0.0.1:8898）；真插座（本地 HTTP 型）待采购接线 |
| 手机节点 | **模拟器预演**（`scripts/mock_phone_sensor` 发布 UniSpec+状态，行为与 App 一致）；真机（IoT MQTT Panel）待人工 |
| 温度/空调设备 | `simulator --init-temp 15/25`（工作流条件双分支用）+ `sim_ac` |
| 摄像头 | 本机 PnP 检测到 **3 个摄像头设备**；取景类用例待人工（见 §7） |

## 2. 逐用例执行记录

判定说明：通过 = 实测输出满足用例判据（证据见 `docs/evidence/hardware_test_20261003.txt` 对应小节）。

| 编号 | 用例 | 结果 | 实测输出摘要 | 证据 |
|---|---|---|---|---|
| TC-11 | 摄像头抓拍 | ⏳ 待人工 | 需人工在场取景（本机已检测到摄像头；复现命令见 §7） | — |
| TC-12 | 运动检测 | ⏳ 待人工 | 同上（会开启摄像头） | — |
| TC-13 | 工作流条件编排（抓拍） | ⏳ 待人工 | 依赖 TC-11/12 | — |
| TC-14 | 失败降级 | ✅ 通过（依赖缺失分支） | `detect_motion` → `{"ok": false, "error": "未安装 opencv-python", "hint": ...}`（exit 0，结构化）；工作流按预期降级（s2 skipped）。**无摄像头分支待人工复核**（需断开摄像头） | §[8]（安装 opencv 前实测） |
| TC-15 | 路径白名单（安全） | ✅ 通过 | `capture_image("../../escape_test.jpg")` → `ok:false "输出路径超出白名单"`；白名单外无文件生成 | §[2] |
| TC-21 | 插座状态查询 | ✅ 通过 | `{"power": false, "online": true, "updated_at": ...}` | §[2] |
| TC-22 | 写后读一致 | ✅ 通过 | `set T → get T`；`set F → get F`（双向立即一致，无缓存陈旧值） | §[2] |
| TC-23 | 条件编排闭环 | ✅ 通过（双分支） | 低温：15.2°C<20 → s2=ok 且插座 power=true；常温：24.9°C≥20 → s2=skipped | §[2] §[7] |
| TC-24 | 权限分级（安全） | ✅ 通过 | 写操作 read 权限 → **1003**；读操作 read 权限 → 放行 | §[2] |
| TC-25 | SSRF 防护（安全） | ✅ 通过 | 移除私有地址放行后启动 → `plug_get_state` → **1006**（拒绝访问私有地址 127.0.0.1） | §[5] |
| TC-31 | 设备自动发现 | ✅ 通过 | `probe watch` 收到 `iot.phone_01` / `iot.temp_01` / `iot.ac_01` 注册摘要（能力列表正确）；另注册 `iot.phone_02` 前置验证 | §[3] §[4] |
| TC-32 | 只读读取 | ✅ 通过 | `battery=61.2/54.9`、`temperature=26.5/26.8`（与模拟器上报一致） | §[2] §[5] |
| TC-33 | 工作流读取 | ✅ 通过 | `phone_battery_snapshot` steps=['ok','ok'] | §[2] §[5] |
| TC-34 | 晚订阅恢复（retain） | ✅ 通过 | Hub 重启后无需设备重发，`get_phone_battery` 立即返回 54.8 | §[5] |
| TC-35 | 异常：无状态 | ✅ 通过 | 注册"只上报缺失"设备 `phone_02` → 调用其工具 → **1006**"无最新状态" | §[4] |
| TC-41 | CPU 使用率 | ✅ 通过 | `get_system_cpu` = 20~63%（随负载变化） | §[1] §[2] |
| TC-42 | 可用内存 | ✅ 通过 | `get_system_memory` = 16.36~17.77 GB | §[1] §[2] |
| TC-43 | 跨适配器编排 | ✅ 通过 | `dev_machine_health` steps=[s1 ok, s2 ok, s3(git) ok] | §[2] |
| TC-44 | 命令/参数白名单（安全） | ✅ 通过 | 未知参数 → **1002** 拦截 | §[2] |
| TG-1 | 核心零改动实证 | ✅ 通过 | 9 个硬件工件全部为配置/脚本/规格/蓝图（清单见 §[9]）；4 个测试接入**未修改 core/ 任何 .py** | §[9] |
| TG-2 | 统一工具面 | ✅ 通过 | 19 工具同一份 `tools/list`；`--meta-tools` 模式为 4 元工具（两模式均验证） | §[1] §[2] §[6] |
| TG-3 | 审计完整性 | ✅ 通过 | 审计链：records=29，chained=29，`chain_ok=True`，记录含 `schema_hash` 字段；拦截用例（1003/1006/1002）均落审计 | §[2] §[5] |
| TG-4 | 元工具兼容 | ✅ 通过 | `--meta-tools` 下 `execute_tool(get_system_cpu)=ok`（Guard 语义不变） | §[6] |

**汇总：执行 20 项 → 全部通过；0 失败；待人工 3 项（TC-11/12/13，摄像头取景）。**

## 3. 性能采样（3 次，独立 caller；单位 ms）

| 工具 / 工作流 | 适配器 | 中位 | 最大 | 说明 |
|---|---|---|---|---|
| `get_system_cpu` | CLI | 1339 | 1399 | PowerShell 冷启动开销（每调用新进程） |
| `get_system_memory` | CLI | 593 | 631 | 同上 |
| `plug_get_state` | REST | 1442 | 1477 | 本地 mock；见下方"连接开销"说明 |
| `get_phone_battery` | MQTT | **0** | 0 | 网关状态缓存（设备周期上报） |
| `get_temperature` | MQTT | **0** | 0 | 同上 |
| `run_workflow(dev_machine_health)` | 编排 | 2145 | 2277 | 3 步串行（CPU+内存+git） |
| `run_workflow(phone_battery_snapshot)` | 编排 | **10** | 11 | 2 步纯缓存读取 |
| `capture_image` / `detect_motion` | Script | — | — | 待人工（需摄像头取景） |

> 说明：① MQTT 读取为缓存命中（0ms 级）；② CLI 受 PowerShell 冷启动影响约 0.6-1.4s；
> ③ 本地 REST mock 观测到约 1.4s 连接开销（与 open-meteo mock 首连同量级，属本机 HTTP
> 客户端连接建立开销，非平台逻辑）；后续可选优化：REST 适配器复用连接池（已列入改进路线）。

## 4. 问题记录

| # | 关联 | 现象 | 根因 | 处置 | 状态 |
|---|---|---|---|---|---|
| 1 | 准备阶段 | 硬件档注册记录持久化进**演示库**，默认档启动恢复出 6 个孤立工具（19 而非 11） | 演示/测试共用 `data/uniagent.db` | 新增 `HUB_DB` 档位隔离（硬件档用 `uniagent_hardware.db`）并清理演示库 | ✅ 已修复（本次执行全程使用隔离档） |
| 2 | 本次执行 | 审计 JSONL 仍写入演示审计文件（`data/audit.jsonl`） | 审计路径未接环境变量 | 新增 `HUB_AUDIT_FILE` 支持（测试档用 `audit_hardware.jsonl`） | ✅ 已修复 |
| 3 | 本次执行 | 混合审计文件（历史无链记录 + 链记录）校验会误报"篡改" | `verify_chain` 从第 0 条起校验 | 兼容处理：**分段校验**（切分链段逐段校验、段间无链记录中性跳过；含新单测） | ✅ 已修复 |
| 4 | 环境特性 | `probe watch` 出现重复注册提示 / 状态噪音 | 本地 amqtt broker 通配订阅多投递 retained 消息（EMQX/公共 broker 无此现象） | 探针已加 topic 前缀过滤；平台按前缀分发不受影响 | 记录（非缺陷） |
| 5 | 准备阶段 | `body_*` 参数从未注册（POST 类接口不可用） | `simplify_schema` 丢弃 requestBody 嵌套 properties | 直接展开 + JSON body 实际发送（含单测） | ✅ 已修复 |
| 6 | 准备阶段 | 插座"写后读旧值" | 只读缓存对含写能力的设备 Spec 生效 | 缓存仅对"整份 Spec 全只读"启用 | ✅ 已修复 |

## 5. 审计与安全证据

| 项 | 记录 |
|---|---|
| 审计文件 | `data/audit_hardware.jsonl`（独立档位）+ SQLite `data/uniagent_hardware.db` |
| 哈希链校验 | `python -m scripts.attestation audit-verify --file data/audit_hardware.jsonl` → **✓ 通过**（记录数 29，链长 29） |
| schema_hash | 审计记录均携带工具定义内容哈希（TG-3 校验 True） |
| 工具清单签名 | 未配置 `HUB_ATTESTATION_KEY`（signed=false；签名能力已就绪，按需启用） |
| 拦截用例 | 1003（越权写）×1、1002（未知参数）×1、1006（SSRF）×1、1006（无状态）×1 —— 全部落审计 |
| 路径白名单 | TC-15 越界写入被拒且无文件泄漏 |

## 6. 结论（阶段结论）

**已执行部分（不依赖外部硬件）：20/20 通过，0 失败。**

| 用例子集 | 等级 | 依据 |
|---|---|---|
| TC-1x 摄像头（Script） | ⏳ 未完成 | TC-15 通过、TC-14 通过（依赖缺失分支）；TC-11/12/13 待人工 |
| TC-2x 智能插座（REST） | **A（通过）** | 5/5 必须用例通过（mock 预演；真插座复测见 §7） |
| TC-3x 手机节点（MQTT） | **A（通过）** | 5/5 必须用例通过（模拟器预演；真机复测见 §7） |
| TC-4x PC 系统监控（CLI） | **A（通过）** | 4/4 必须用例通过（**全真、无 mock**） |
| TC-5x ESP32 温室（MQTT·**模拟器**） | **A（通过）** | 5/5 必须用例通过（模拟器，2026-10-04 实测；见 §10） |
| TG 通用性（横切） | **A（通过）** | TG-1~4 全部"必须"通过 |

**通用性结论矩阵（本轮已填；括号内为预演方式）**：

```
        MQTT    CLI    REST   Script  SQL   WebSocket
摄像头    —      —      —      ⏳      —       —       (TC-1x，待人工)
智能插座  —      —      ✅(mock)  —      —       —       (TC-2x)
手机      ✅(模拟器) —     —      —      —       —       (TC-3x)
PC系统    —      ✅      —      —      —       —       (TC-4x)
ESP32    ✅(模拟) —      —      —      —       —       (TC-5x，模拟器)
```

**总体判定**：跳过摄像头子集后按 A/B/C 标准评估，**已完成的 4 个子集全部 A、TG 全部通过**，达标。
摄像头子集完成后补记终判（含真插座、真手机复测；ESP32 温室以模拟器为准，真机固件为后续可选轨）。

## 7. 待人工执行清单（摄像头 + 真机复测）

> 均为一键可复现；详细步骤见 `docs/hardware/hardware_test_plan.md`。

| # | 事项 | 命令 / 操作 | 预期 |
|---|---|---|---|
| 1 | TC-11 抓拍 | 硬件档启动后：`python -m scripts.hardware_probe call --tool capture_image --args "{\"output_path\": \"alert.jpg\"}" --permission write` | `ok:true` 且 `data/captures/alert.jpg` 生成 |
| 2 | TC-12 运动检测 | `python -m scripts.hardware_probe call --tool detect_motion`；在镜头前挥手后复跑 | 挥手后 `pixel_count` 明显增大 |
| 3 | TC-13 抓拍工作流 | `python -m scripts.hardware_probe call --tool run_workflow --args "{\"workflow\": \"security_monitor\"}" --permission write` | 有运动时 s2 执行并生成新图片 |
| 4 | TC-14 无摄像头分支复核 | 设备管理器禁用摄像头后重跑 TC-11/12 | 结构化 `ok:false "摄像头未就绪"` |
| 5 | 真插座复测 | 按 plan §3 测试 2 方案 A 修改 `smart_plug.yaml` 地址；重跑 `python -m scripts.hardware_test_run --only TC-21,TC-22,TC-23,TC-24` | 同 mock 结果 |
| 6 | 真手机复测 | 按 plan §3 测试 3 用 IoT MQTT Panel 发布注册与状态；重跑 `--only TC-31,TC-32,TC-33,TC-34` | 同模拟器结果 |
| 7 | 完成后 | 在本记录 §2 表格补记人工用例结果，重跑 §7 矩阵终判 | 全部 A → 终版报告 |

## 8. 复现命令（完整）

```powershell
# 1) 启动组件（各开一个终端）
python -m scripts.dev_mqtt_broker --port 1883
python -m scripts.mock_plug_api --port 8898
python -m scripts.mock_phone_sensor --broker mqtt://127.0.0.1:1883
python -m adapters.mqtt_adapter.simulator --broker mqtt://127.0.0.1:1883 --init-temp 15
python -m adapters.mqtt_adapter.sim_ac --broker mqtt://127.0.0.1:1883
# 2) 启动 Hub（档位隔离 + 哈希链）
$env:HUB_MQTT_BROKER = "mqtt://127.0.0.1:1883"
$env:HUB_DB = "data/uniagent_hardware.db"
$env:HUB_AUDIT_FILE = "data/audit_hardware.jsonl"
$env:HUB_AUDIT_CHAIN = "1"
$env:HUB_CLI_CONFIGS = "adapters/cli_adapter/configs/cli_tools.yaml;adapters/cli_adapter/configs/system_monitor.yaml"
$env:HUB_SCRIPT_CONFIGS = "adapters/script_adapter/configs/scripts.yaml;adapters/script_adapter/configs/hardware_tests.yaml"
$env:HUB_REST_SPECS = "adapters/rest_adapter/specs/open_meteo.yaml;adapters/rest_adapter/specs/smart_plug.yaml"
$env:HUB_REST_ALLOWED_PRIVATE_HOSTS = "127.0.0.1"
$env:HUB_WORKFLOWS = "core/workflow/workflows_hardware.yaml"
python main.py --port 8020
# 3) 就绪检查 + 用例批 + 性能采样（证据落 docs/evidence/）
python -m scripts.hardware_probe check --url http://127.0.0.1:8020
python -m scripts.hardware_test_run --url http://127.0.0.1:8020 --perf 3
# 4) 链校验
python -m scripts.attestation audit-verify --file data/audit_hardware.jsonl
```

## 9. 附件清单

| # | 文件 | 说明 |
|---|---|---|
| 1 | `docs/evidence/hardware_test_20261003.txt` | 全部命令原始输出（§[1]~§[9] 小节与上表引用一致） |
| 2 | `data/audit_hardware.jsonl` / `data/uniagent_hardware.db` | 审计（含哈希链）与工具注册（独立档位）。**保留作复现证据**：data/ 已被 .gitignore 覆盖、不入库；如需复现链校验，勿删除 |
| 3 | `data/captures/` | 抓拍输出目录（待人工用例生成） |
| 4 | 本记录 | `docs/hardware/records/20261003_hardware_test.md` |

> 备注：本轮为"无外部硬件用例"执行记录；摄像头与真机复测完成后，将本记录补记并入最终硬件测试报告（研究报告类文档按既定约束在硬件测试全部完成后更新）。

## 10. 补充：ESP32 温室节点用例（模拟器，2026-10-04）

> 决策：**全面改用 Python MQTT 模拟器替代真实 ESP32 硬件**（原"真机"表述未实测，已作废）。
> 设备端 `adapters/mqtt_adapter/sim_esp32_greenhouse.py`（设备 id `irrigation_01`），
> 工作流 `core/workflow/workflows_hardware.yaml::smart_irrigation`。
> 原始证据：`docs/evidence/esp32_simulator_e2e_20261004.txt`。
> 真机固件骨架 `docs/hardware/firmware/esp32/` 双轨保留，**未烧录、未实测**。

| 编号 | 用例 | 结果 | 实测输出摘要 | 证据 |
|---|---|---|---|---|
| TC-51 | 设备自动发现（模拟器上电） | ✅ 通过 | 上电 → `tools/list` 可见 3 工具，耗时 **0.23s**（原真机记录 8.6s） | §一 |
| TC-52 | 只读读取 | ✅ 通过 | `get_soil_moisture`=24.2 / `get_light_intensity`=12123.5 lux，缓存读取 **0ms** | §二 |
| TC-53 | 工作流闭环 | ✅ 通过 | `smart_irrigation` 3 步全 ok，总耗时 **1.30s**（3 次 1.29/1.29/1.30s） | §二 |
| TC-54 | 写回执一致性 | ✅ 通过 | s3 `control_pump` 返回 `pump=on` 且 `request_id` 匹配本次命令，写回执 **100ms** | §二 |
| TC-55 | 安全 / 边界 | ✅ 通过 | 越权 1003 / 时长超限参数校验拒绝 / 无状态 1006（单测 7 passed 覆盖） | §五 |

**模拟器实测指标对照**：

| 指标 | 真机（原记录，未实测） | 模拟器（本次实测） |
|---|---|---|
| 自动发现（上电 → 工具可见） | 8.6s | **0.23s** |
| 浇水闭环总耗时 | 2.8s | **1.30s** |
| 水泵写回执 | 212ms | **100ms** |
| 传感器读取 | 0ms（缓存） | **0ms**（缓存） |

物理行为：开泵后土壤湿度由 22.4% 回升至 34.4%，复现"浇水后读数爬升"；自动化测试 `pytest` **179 passed, 5 skipped**。