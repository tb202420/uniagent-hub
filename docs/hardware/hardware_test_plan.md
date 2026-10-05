# 硬件通用性测试 — 环境配置方案

> 依据：`项目改进方案/硬件通用性测试方案.txt`；配套代码与配置已在本仓库就绪（见各测试"文件清单"）。
> 目标：用 4 类真实硬件 + 1 类模拟节点（ESP32 温室，Python MQTT 模拟器）证明同一平台"**配置即接入、核心零改动**"。
> 前置说明：**本文件只做测试准备**；接线与实测为人工操作，请按 §6 记录模板留证。

## 1. 总览

| # | 测试 | 硬件 | 适配器 | 平台侧工作量 | 无硬件预演 |
|---|---|---|---|---|---|
| 1 | USB 摄像头监控 | USB 摄像头（UVC） | Script | ~55 行脚本 + 1 份 YAML | 无摄像头/未装 opencv 时返回结构化错误 |
| 2 | 智能插座 | 智能插座（本地 HTTP） | REST | 0 行（OpenAPI 配置） | `scripts/mock_plug_api.py`（端口 8898） |
| 3 | 手机传感器节点 | Android 手机 + IoT MQTT Panel | MQTT | 0 行（App 配置） | `scripts/mock_phone_sensor.py` |
| 4 | PC 系统监控 | 无（PC 自身） | CLI | 0 行（YAML 配置） | 直接可用（已实测） |
| 5 | ESP32 温室灌溉 | ESP32-S3 温室节点（**Python MQTT 模拟器**；真机固件为后续可选轨） | MQTT | 0 行（设备端模拟器） | 模拟器直接可用（`sim_esp32_greenhouse`，已实测） |

## 2. 通用环境准备

### 2.1 软件依赖

```powershell
# 测试 1 需要（其余测试不需要）
& "C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe" -m pip install opencv-python
```

### 2.2 一键启动硬件测试档（含 mock 组件）

```powershell
# 终端 A：本地 MQTT broker（离线可复现；比赛环境可换 EMQX）
python -m scripts.dev_mqtt_broker --port 1883
# 终端 B：mock 智能插座（测试 2 预演用；接真插座后可不启）
python -m scripts.mock_plug_api --port 8898
# 终端 C：手机传感器模拟器（测试 3 预演用；手机就绪后可不启）
python -m scripts.mock_phone_sensor --broker mqtt://127.0.0.1:1883
# 终端 D：温度模拟器（演示设备；office_auto_light 工作流用）
python -m adapters.mqtt_adapter.simulator --broker mqtt://127.0.0.1:1883 --init-temp 15
# 终端 D2：ESP32 温室节点模拟器（测试 5；替代真机，真机固件为后续可选轨）
python -m adapters.mqtt_adapter.sim_esp32_greenhouse --broker mqtt://127.0.0.1:1883 --init-soil 25
# 终端 E：Hub（硬件测试档：默认配置 + 三份硬件配置 + 硬件工作流）
$env:HUB_MQTT_BROKER = "mqtt://127.0.0.1:1883"
$env:HUB_DB = "data/uniagent_hardware.db"   # 档位隔离：测试注册/审计写入独立库，不污染演示库
$env:HUB_AUDIT_FILE = "data/audit_hardware.jsonl"   # 审计 JSONL 一并隔离（配合哈希链便于独立校验）
$env:HUB_CLI_CONFIGS = "adapters/cli_adapter/configs/cli_tools.yaml;adapters/cli_adapter/configs/system_monitor.yaml"
$env:HUB_SCRIPT_CONFIGS = "adapters/script_adapter/configs/scripts.yaml;adapters/script_adapter/configs/hardware_tests.yaml"
$env:HUB_REST_SPECS = "adapters/rest_adapter/specs/open_meteo.yaml;adapters/rest_adapter/specs/smart_plug.yaml"
$env:HUB_REST_ALLOWED_PRIVATE_HOSTS = "127.0.0.1"
$env:HUB_WORKFLOWS = "core/workflow/workflows_hardware.yaml"
python main.py --port 8020
```

启动后应看到：`[hub] 已注册 22 个工具`（软件档 11 + 温室模拟节点 3 + 硬件专测 8；若未启动终端 D2 温室模拟器则为 19）、
`工作流已加载: [... security_monitor, office_auto_light, phone_battery_snapshot, dev_machine_health, smart_irrigation]`。

### 2.3 调试探针（推荐先跑）

```powershell
# 就绪检查：预期工具是否注册 + 只读工具逐个实测
python -m scripts.hardware_probe check --url http://127.0.0.1:8020
# 监听设备注册（调试新设备上线：应先看到 UniSpec 摘要）
python -m scripts.hardware_probe watch --broker mqtt://127.0.0.1:1883 --seconds 30
# 调用任意工具（写操作加 --permission write）
python -m scripts.hardware_probe call --tool plug_set_power --args "{\"body_power\": true}" --permission write
```

### 2.4 平台侧文件清单

| 文件 | 用途 |
|---|---|
| `adapters/script_adapter/scripts/camera_capture.py` | 测试 1：摄像头抓拍 / 运动检测（含路径白名单） |
| `adapters/script_adapter/configs/hardware_tests.yaml` | 测试 1：脚本工具注册（`capture_image` / `detect_motion`） |
| `adapters/rest_adapter/specs/smart_plug.yaml` | 测试 2：插座 OpenAPI 规格（`plug_get_state` / `plug_set_power`） |
| `scripts/mock_plug_api.py` | 测试 2：本地 Mock 插座（无硬件预演） |
| `scripts/mock_phone_sensor.py` | 测试 3：手机节点模拟器（无手机预演） |
| `adapters/cli_adapter/configs/system_monitor.yaml` | 测试 4：CPU / 内存 CLI 工具（`get_system_cpu` / `get_system_memory`） |
| `adapters/mqtt_adapter/sim_esp32_greenhouse.py` | 测试 5：ESP32 温室节点模拟器（设备 id `irrigation_01`；土壤/光照读取 + 水泵控制，替代真机） |
| `core/workflow/workflows_hardware.yaml` | 4 个测试的工作流蓝图（`security_monitor` 等）+ 测试 5 的 `smart_irrigation` |
| `scripts/hardware_probe.py` | 调试探针（check / call / watch） |

## 3. 分测试环境配置

### 测试 1：USB 摄像头（Script 适配器）

- **硬件**：任意 UVC 摄像头（约 50 元）插入 PC USB 口；Windows 自动识别（设备管理器出现"摄像头"）。
- **依赖**：`opencv-python`（§2.1）。
- **配置**：已在 `hardware_tests.yaml` 注册；输出目录 `data/captures/`（可用 `HUB_CAPTURE_DIR` 覆盖）。
- **执行**：
  ```powershell
  python -m scripts.hardware_probe call --tool detect_motion
  python -m scripts.hardware_probe call --tool capture_image --args "{\"output_path\": \"alert.jpg\"}" --permission write
  python -m scripts.hardware_probe call --tool run_workflow --args "{\"workflow\": \"security_monitor\"}" --permission write
  ```
- **预期**：`detect_motion` 返回 `{"ok": true, "motion_detected": ..., "pixel_count": N}`；
  抓拍生成 `data/captures/alert.jpg`；有运动（pixel_count>5000）时工作流自动抓拍。
- **安全验证**：`output_path` 传 `"../../windows/system32/x.jpg"` 应被拒绝（路径白名单）。

### 测试 2：智能插座（REST 适配器）

- **方案 A（立即可测）**：本地 HTTP 插座（Tasmota / Shelly / 自建 ESP 继电器）。
  改 `smart_plug.yaml` 的 `servers.url` 为设备地址（如 `http://192.168.1.50`），
  并把该 IP 加入 `HUB_REST_ALLOWED_PRIVATE_HOSTS`。
- **方案 B（预演）**：`scripts/mock_plug_api.py`（默认配置已指向 `http://127.0.0.1:8898`）。
- **方案 C（Tuya 云，暂不可用）**：Tuya/米家云 API 需 HMAC 签名认证，
  当前适配器仅支持 API Key 注入 → **列入批 5"签名认证插件"**（见 improvement_plan §4）。
- **执行**：
  ```powershell
  python -m scripts.hardware_probe call --tool plug_get_state
  python -m scripts.hardware_probe call --tool plug_set_power --args "{\"body_power\": true}" --permission write
  python -m scripts.hardware_probe call --tool run_workflow --args "{\"workflow\": \"office_auto_light\"}" --permission write
  ```
- **预期**：`plug_set_power` 后 `plug_get_state` **立即反映新状态**（设备类 Spec 已禁用只读缓存）；
  室温 <20°C 时 `office_auto_light` 自动开插座（温度模拟器 `--init-temp 15` 可复现）。

### 测试 3：手机传感器节点（MQTT 适配器）

- **手机端（约 5 分钟，人工）**：安装 **IoT MQTT Panel**（免费）：
  1. 连接 broker：演示同网段用 PC 本地 broker `192.168.x.x:1883`，或公共 `broker.emqx.io:1883`；
  2. 发布主题 `uniagent-hub-rxyc/register/phone_01`（retain），内容 = UniSpec（见下）；
  3. 定时/手动发布 `uniagent-hub-rxyc/devices/phone_01/state`，内容
     `{"battery": 78, "temperature": 26.5}`。
- **UniSpec（直接复制到 App 发布框）**：
  ```json
  {"id": "iot.phone_01", "type": "iot_device", "name": "手机传感器节点", "protocol": "mqtt",
   "endpoint": {"broker": "mqtt://<PC_IP>:1883", "topic": "uniagent-hub-rxyc/devices/phone_01/state"},
   "capabilities": [
     {"name": "get_phone_battery", "description": "手机电量（%）", "stateField": "battery", "readOnly": true},
     {"name": "get_phone_temperature", "description": "手机温度（℃）", "stateField": "temperature", "readOnly": true}],
   "constraints": {"readOnly": true, "permissionLevel": "read", "rateLimit": "10/m", "timeout": "3s"}}
  ```
- **预演**：不接手机时用 `scripts.mock_phone_sensor.py`（行为与 App 完全一致：注册 + 周期上报）。
- **执行与预期**：`probe watch` 应先看到 `iot.phone_01` 注册；
  `get_phone_battery` 返回数值；`run_workflow phone_battery_snapshot` 两步 ok。

### 测试 4：PC 系统监控（CLI 适配器）

- **硬件**：无（PC 自身）。
- **配置**：`system_monitor.yaml`（命令已针对**中文 Windows** 选型：
  使用 `Get-CimInstance`，不用 `Get-Counter` 英文计数器名——中文系统上会解析失败）。
- **执行**：
  ```powershell
  python -m scripts.hardware_probe call --tool get_system_cpu
  python -m scripts.hardware_probe call --tool get_system_memory
  python -m scripts.hardware_probe call --tool run_workflow --args "{\"workflow\": \"dev_machine_health\", \"params\": {\"repo\": \"D:/projec_UniAgent Hub\"}}" --permission write
  ```
- **预期**：CPU 0-100、内存 GB 数值；`dev_machine_health` 三步 ok（CPU + 内存 + git 状态）。

### 测试 5：ESP32 温室节点（MQTT 适配器 · 模拟器）

- **硬件（模拟）**：**Python MQTT 模拟器** `adapters/mqtt_adapter/sim_esp32_greenhouse.py`（设备 id `irrigation_01`），
  替代真实 ESP32-S3 温室节点。真机固件骨架 `docs/hardware/firmware/esp32/` 双轨保留，**未烧录、未实测**，为后续可选轨。
- **启动**：`python -m adapters.mqtt_adapter.sim_esp32_greenhouse --broker mqtt://127.0.0.1:1883 --init-soil 25`
  （`--init-soil 25` 让土壤湿度低于阈值 30，触发浇水条件；默认 45 则不触发）。
- **预演**：模拟器上线即发布 UniSpec(retain)，自动被 Hub 发现，无需其它组件。
- **执行**：
  ```powershell
  python -m scripts.hardware_probe call --tool get_soil_moisture
  python -m scripts.hardware_probe call --tool get_light_intensity
  python -m scripts.hardware_probe call --tool run_workflow --args "{\"workflow\": \"smart_irrigation\"}" --permission write
  ```
- **预期**：3 个温室工具注册可见（自动发现约 0.23s）；`smart_irrigation` 三步全 ok（读土壤 → 读光照 → 条件开泵），
  总耗时约 1.30s；`control_pump` 写回执约 100ms；开泵后土壤湿度回升。
- **安全验证**：`control_pump` 不带 `--permission write` 应被 1003 拒绝；`duration` 超过 600s 被参数校验拒绝。

## 4. 已知现象与故障速查（实测后补充，2026-10-03）

| 现象 | 原因 | 处置 |
|---|---|---|
| `detect_motion` 返回 `{"ok": false, "error": "未安装 opencv-python"}` | 未安装依赖 | `pip install opencv-python` 后重跑 |
| `security_monitor` 的抓拍步骤被跳过 | 无运动（`pixel_count ≤ 5000`）或摄像头未就绪（失败时 pixel_count=0） | 属预期；看 s1 输出中的 `error/hint` 字段 |
| `plug_set_power` 返回 SSRF 拦截 | 私有地址未放行 | 设 `HUB_REST_ALLOWED_PRIVATE_HOSTS=127.0.0.1`（或设备 IP） |
| 插座读到旧状态 | 历史版本缓存问题 | 已修复：设备类 Spec（含写能力）禁用只读缓存；如仍异常，重启 Hub 加载新代码 |
| 离线档 `probe watch` 出现重复注册提示/状态噪音 | 本地 amqtt broker 通配订阅多投递 retained 消息（EMQX/公共 broker 无此现象） | 探针已内置 topic 前缀过滤；平台按 topic 前缀分发不受影响 |
| `get_temperature` 报"无负责适配器" | 温度模拟器未启动（注册消息缺失） | 启动 `simulator --broker ... --init-temp 15` |
| 温度不触发 `office_auto_light` | 室温 ≥20°C（本机常温 26-31） | 用 `--init-temp 15` 重启模拟器复现"低温开插座" |

## 5. 安全注意事项

- **路径白名单**：抓拍输出被限制在 `data/captures/`（`HUB_CAPTURE_DIR`）之下，`../` 逃逸会被脚本与 Guard 双重拒绝；
- **权限分级**：`capture_image` / `plug_set_power` 为 write 级（需 `--permission write`）；只读工具默认放行；
- **SSRF 防护**：仅 `HUB_REST_ALLOWED_PRIVATE_HOSTS` 显式列出的主机可访问私有地址；
- **审计留痕**：所有调用（含被拦截）落 `data/audit.jsonl` + SQLite，含 `schema_hash` 与错误码；
  建议测试同时开启哈希链：`$env:HUB_AUDIT_CHAIN="1"`（配合 `python -m scripts.attestation audit-verify` 校验）。

## 6. 记录与留证

按 `docs/hardware/hardware_test_record_template.md` 逐项记录；证据建议包含：
终端截图（工具返回 + probe 输出）、`data/captures/` 生成图片、手机 App 发布截图、
审计导出（`python -m scripts.attestation audit-verify --file data/audit.jsonl`）、失败现象截图。