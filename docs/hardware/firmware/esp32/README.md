# ESP32-S3 温室灌溉节点固件（真机轨）

与 Python 模拟器（`adapters/mqtt_adapter/sim_esp32_greenhouse.py`）**同一行为契约**：
上电注册 UniSpec（retain）→ 30s 周期状态上报 → 命令回执（request_id）→ 600s 自动停泵 → 断线指数退避重连。
契约回归测试：`tests/unit/test_firmware_contract.py`（无需真机与编译器）。

## 接线（默认引脚，改 `src/main.cpp` 顶部 PIN_* 常量）

| 部件 | 引脚 | 说明 |
|---|---|---|
| 电容土壤湿度 | GPIO4（ADC） | 干 ~3200mV / 湿 ~1300mV，校准常量 `SOIL_MV_DRY/WET` |
| DHT22 温湿度 | GPIO5（DATA） | 需 4.7kΩ 上拉；位带直驱，无需外部库 |
| BH1750 光照 | I2C：SDA=GPIO8 / SCL=GPIO9 | 地址 0x23 |
| 继电器（水泵） | GPIO10（IN） | 默认高电平吸合（`RELAY_ACTIVE_HIGH` 可反） |

## 烧录三步（凭据放 `src/secrets.h`，不入库）

```bash
# 1) 创建 src/secrets.h（参照下方模板；该文件已被 .gitignore 排除）：
#      #define WIFI_SSID  "你的WiFi名"
#      #define WIFI_PASS  "你的WiFi密码"
#      #define MQTT_HOST  "192.168.5.21"     # broker 所在机器（本地联调=PC 内网 IP）
#      #define MQTT_PORT  1883
#    无 secrets.h 时使用 main.cpp 内占位默认值，克隆即编译
# 2) 编译 + 烧录（PIO CLI；或 VSCode PlatformIO 的 Upload 按钮）
pio run -d docs/hardware/firmware/esp32 -t upload
# 3) 串口监视（115200）
pio device monitor -d docs/hardware/firmware/esp32
```

编译实测（2026-10-24）：ArduinoJson 7.4.3 + PubSubClient 2.8.0，RAM 15.2% / Flash 24.4%。
真机联调实测（2026-10-24，`docs/evidence/real_device_e2e_20261024.txt`）：
自动发现 retain 注册 ✓ / 命令→回执 avg 152ms / 自动停泵 5.1s 精确自停 /
经 Hub Guard 全链路 100ms / 审计含 schema_hash。

## 硬件成本表（低成本可复制）

| 部件 | 参考价（元） |
|---|---|
| ESP32-S3-DevKitC-1 | ~35 |
| DHT22 温湿度模块 | ~10 |
| BH1750 光照模块 | ~8 |
| 电容土壤湿度探头 | ~8 |
| 5V 继电器模块 | ~6 |
| 微型水泵 + 硅胶管 | ~15 |
| USB 电源/线材/面包板 | ~10 |
| **合计** | **约 92**（研究报告口径 80–130 元一致） |

## 验收清单（规划里程碑 1：MQTTX 能看到三个 topic）

1. 串口出现 `MQTT 已连接`、`UniSpec 注册(retain,ok)`、`已订阅 .../command`；
2. MQTTX 订阅 `uniagent-hub-rxyc/#`：
   - `register/irrigation_01` 收到 retain UniSpec（3 能力）；
   - `devices/irrigation_01/state` 每 30s 一帧（soil_moisture/light_intensity/pump/ts…）；
   - 向 `devices/irrigation_01/command` 发布 `{"action":"on","duration":10,"request_id":"r1"}`
     → 继电器吸合 + state 帧立即回执（request_id=r1）→ 10s 后自动停泵帧；
3. 启动 Hub（`python main.py`）→ `tools/list` 出现 `get_soil_moisture / get_light_intensity / control_pump`；
   `run_workflow {"workflow":"smart_irrigation"}` 全链路 ok（建议先停模拟器，二者设备 id 相同会互相覆盖注册）。

## 能力集开关

- 默认 3 能力（soil/light/pump）：与模拟器及演示档"温室节点 3 工具"口径一致。
- `FULL_CAPABILITIES 1`：追加 `get_temperature` / `get_humidity`（DHT22）。
  ⚠️ 基础档空调模拟器已占用这两个工具名——同场运行需设 `TOOL_PREFIX "gh_"` 或停用空调模拟器。

## 其他开关

- `ENABLE_OTA 1`：局域网 ArduinoOTA（PlatformIO Upload via OTA / arduino-ota 工具）。
- `MQTT_TLS 1`：MQTT over TLS（8883），需先把完整根证书 PEM 粘贴进 `kRootCA`
  （broker.emqx.io:8883 用 Let's Encrypt → ISRG Root X1）。**粘贴占位内容直接启用会连接失败。**

## 已知差异（如实声明）

PubSubClient 的 publish 仅 QoS0；Hub 端 paho 订阅同为 QoS0，链路语义等价
（模拟器侧 qos=1 是其客户端默认值）。需要 QoS1 发布时后续可换 espMqttClient。
