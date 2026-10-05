# 硬件通用性测试 — 兼容性测试用例与评估标准

> 配套：`docs/hardware/hardware_test_plan.md`（环境配置）· `docs/hardware/hardware_test_record_template.md`（记录模板）
> 规则：每条用例"通过/不通过"必须附证据（终端输出或截图）；不做主观判定。

## 1. 用例总览

| 用例子集 | 覆盖 | 用例数 |
|---|---|---|
| TC-1x 摄像头（Script 适配器） | 正常 / 边界 / 失败降级 / 安全 | 5 |
| TC-2x 智能插座（REST 适配器） | 正常 / 状态一致 / 条件编排 / 安全 | 5 |
| TC-3x 手机节点（MQTT 适配器） | 自动发现 / 只读读取 / 工作流 / 异常 | 5 |
| TC-4x PC 系统监控（CLI 适配器） | 正常 / 跨适配器编排 / 安全 | 4 |
| TC-5x ESP32 温室节点（MQTT 适配器 · **模拟器**） | 自动发现 / 只读读取 / 工作流闭环 / 写回执 / 安全 | 5 |
| TG-x 平台通用性（横切） | 核心零改动 / 审计 / 权限 / 元工具 | 4 |

> 硬件口径：**4 类真实硬件**（TC-1x 摄像头 / TC-2x 智能插座 / TC-3x 手机节点 / TC-4x PC 系统监控）
> **+ 1 类模拟节点**（TC-5x ESP32 温室，Python MQTT 模拟器）。真机固件为后续可选轨，未烧录、未实测。

## 2. 测试 1：USB 摄像头（Script 适配器）

| 编号 | 用例 | 步骤 | 通过判据 | 等级 |
|---|---|---|---|---|
| TC-11 | 摄像头识别与抓拍 | `probe call --tool capture_image --args '{"output_path": "alert.jpg"}' --permission write` | 返回 `{"ok": true, "path": ...}` 且 `data/captures/alert.jpg` 存在（可打开） | **必须** |
| TC-12 | 运动检测（静态场景） | `probe call --tool detect_motion` | 返回 `ok: true` 且 `pixel_count` 为整数；人为在镜头前挥手后 `pixel_count` 明显增大 | **必须** |
| TC-13 | 工作流条件编排 | `probe call --tool run_workflow --args '{"workflow": "security_monitor"}' --permission write` | 挥手时 s2 `capture_image` 执行（生成新图片）；静止时 s2 状态为 `skipped` | **必须** |
| TC-14 | 失败降级（无摄像头/无依赖） | 拔掉摄像头或卸载 opencv 后重跑 TC-11/12 | 返回结构化 JSON（`ok:false` + `error/hint`），**不崩溃、不返回 1999** | **必须** |
| TC-15 | 路径白名单（安全） | `capture_image --output_path "../../x.jpg"` | 被拒（`ok:false` 或 1007/1999），`data/captures` 之外无文件生成 | **必须** |

## 3. 测试 2：智能插座（REST 适配器）

| 编号 | 用例 | 步骤 | 通过判据 | 等级 |
|---|---|---|---|---|
| TC-21 | 状态查询 | `probe call --tool plug_get_state` | 返回 `{"power": ..., "online": true}` | **必须** |
| TC-22 | 开关控制与写后读一致 | `plug_set_power(true)` → 立即 `plug_get_state` | 第二次读取立即反映 `power: true`（**无缓存陈旧值**） | **必须** |
| TC-23 | 条件编排闭环 | 温度模拟器 `--init-temp 15` → `run_workflow office_auto_light` | s1 ≤20 → s2 执行且插座状态变为开；把温度设 25 重跑 → s2 `skipped` | **必须** |
| TC-24 | 权限分级（安全） | `plug_set_power` 不带 `--permission write`（read 权限） | 返回 1003 拒绝；`plug_get_state` 同权限放行 | **必须** |
| TC-25 | SSRF 防护（安全） | 移除 `HUB_REST_ALLOWED_PRIVATE_HOSTS` 后启动 Hub，再调 `plug_get_state` | 返回 1006（SSRF 拦截） | 建议 |

## 4. 测试 3：手机传感器节点（MQTT 适配器）

| 编号 | 用例 | 步骤 | 通过判据 | 等级 |
|---|---|---|---|---|
| TC-31 | 设备自动发现 | 手机发布注册 UniSpec（retain）后 `probe watch --seconds 30` | 30s 内看到 `iot.phone_01` 注册摘要（能力 2 项） | **必须** |
| TC-32 | 只读读取 | `probe call --tool get_phone_battery` / `get_phone_temperature` | 返回数值且与 App 发布值一致（±0.1） | **必须** |
| TC-33 | 工作流读取 | `run_workflow phone_battery_snapshot` | 两步 `ok`，输出为电量与温度 | **必须** |
| TC-34 | 晚订阅恢复（retain 机制） | Hub 重启后再读 `get_phone_battery` | 无需手机重发即可读到状态（retain 生效） | **必须** |
| TC-35 | 异常：无状态 | 手机停止上报 60s 后重启 Hub 前读取（或换未上报过的设备） | 返回 1006"无最新状态"，且审计有记录 | 建议 |

## 5. 测试 4：PC 系统监控（CLI 适配器）

| 编号 | 用例 | 步骤 | 通过判据 | 等级 |
|---|---|---|---|---|
| TC-41 | CPU 使用率 | `probe call --tool get_system_cpu` | 返回 0-100 数值；开大负载进程后数值上升 | **必须** |
| TC-42 | 可用内存 | `probe call --tool get_system_memory` | 返回 GB 数值（如 17.x），与任务管理器量级一致 | **必须** |
| TC-43 | 跨适配器编排 | `run_workflow dev_machine_health --params {"repo": "<仓库路径>"}` | 三步全 ok（CPU + 内存 + git 状态），且 git 输出与仓库现状一致 | **必须** |
| TC-44 | 命令白名单（安全） | 检查注册表：`allowed_commands=["powershell"]`；尝试在 `get_system_cpu` 传未知参数 | 未知参数被 1002 拦截（参数白名单生效） | 建议 |

## 6. 测试 5：ESP32 温室节点（MQTT 适配器 · 模拟器）

> 设备侧为 **Python MQTT 模拟器**（替代真机）：`adapters/mqtt_adapter/sim_esp32_greenhouse.py`，
> 设备 id `irrigation_01`，发布 UniSpec(retain) 即被自动发现。启动：
> `python -m adapters.mqtt_adapter.sim_esp32_greenhouse --broker mqtt://127.0.0.1:1883 --init-soil 25`

| 编号 | 用例 | 步骤 | 通过判据 | 等级 |
|---|---|---|---|---|
| TC-51 | 设备自动发现（模拟器上电） | 启动模拟器后 `probe check` / `tools/list` | **0.23s** 内出现 3 工具 `get_soil_moisture` / `get_light_intensity` / `control_pump` | **必须** |
| TC-52 | 只读读取 | `probe call --tool get_soil_moisture` / `get_light_intensity` | 返回数值（如土壤 25.0 / 光照 12000.0 lux）；缓存读取 **0ms** | **必须** |
| TC-53 | 工作流闭环 | 干土（`--init-soil 25`）后 `run_workflow smart_irrigation` | 3 步全 ok，总耗时约 **1.30s**；开泵后土壤湿度回升（22.4%→34.4%） | **必须** |
| TC-54 | 写回执一致性 | 同上 s3 `control_pump`（`action=on`） | 返回 `pump=on` 且 `request_id` 等于本次命令 trace_id；写回执 **100ms** | **必须** |
| TC-55 | 安全 / 边界（安全） | ①`control_pump` 不带 `--permission write`；②`duration` 超 600s；③引用未上报状态的设备 | ①越权 **1003**；②参数校验拒绝（超出时长上限）；③**1006** 无最新状态 | 建议 |

## 7. 平台通用性（横切验证，各测试共用）

| 编号 | 用例 | 步骤 | 通过判据 | 等级 |
|---|---|---|---|---|
| TG-1 | "核心零改动"实证 | `git log --stat` 检视本批硬件相关提交 | 硬件接入改动**不涉及** `core/gateway`、`core/workflow`、`core/guard` 的逻辑（仅配置/脚本/规格新增） | **必须** |
| TG-2 | 统一工具面 | `probe check`（预期 8 个硬件工具全部注册） | 22 工具同一份 `tools/list`（软件档 11 + 温室模拟 3 + 硬件 8；未叠加模拟器时为 19）；Agent 侧无法区分适配器类型 | **必须** |
| TG-3 | 审计完整性 | 上述全部调用后导出审计（`scripts/attestation.py audit-verify` + JSONL） | 每次调用均有记录（含被拦截），错误码/`schema_hash` 字段齐全；哈希链校验通过 | **必须** |
| TG-4 | 元工具兼容（可选） | 以 `--meta-tools` 重启 Hub 后重复 TG-2 | `tools/list` 为 4 元工具；`execute_tool` 调用硬件工具语义不变 | 建议 |

## 8. 评估标准

**单用例判定**：通过 / 不通过（必须附证据）。

**子集（每类硬件 / 模拟节点）评估**：

| 等级 | 标准 |
|---|---|
| **A（通过）** | 全部"必须"用例通过 |
| **B（部分通过）** | "必须"用例通过 ≥ 80%，且失败项有根因定位与处置结论 |
| **C（不通过）** | 其余情况（须记录阻塞原因并转入问题清单） |

**总体达标线**：4 类真实硬件测试中 **≥3 个达到 A、其余不低于 B**，
且 TG 组与 TC-5x（ESP32 温室节点模拟器）全部"必须"通过。

**通用性结论矩阵**（完成后填写 ✅/—）：

```
        MQTT    CLI    REST   Script  SQL   WebSocket
摄像头    —      —      —      ✅      —       —       (TC-1x)
智能插座  —      —      ✅      —      —       —       (TC-2x)
手机      ✅      —      —      —      —       —       (TC-3x)
PC系统    —      ✅      —      —      —       —       (TC-4x)
ESP32    ✅      —      —      —      —       —       (TC-5x，模拟)
```

> 一句话结论（完成后填写）：**__ 类硬件、__ 类适配器、核心零改动** —— 协议无关工具集成的工程实证。