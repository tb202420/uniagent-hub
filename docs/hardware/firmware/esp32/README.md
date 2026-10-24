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

## 烧录三步

```bash
# 1) 填写 src/main.cpp 顶部：WIFI_SSID / WIFI_PASS / MQTT_HOST（Hub 所在网络可达的 broker；
#    本地联调推荐 PC 上起本地 broker：python -m scripts.dev_mqtt_broker --port 1883，
#    MQTT_HOST 填 PC 内网 IP）
# 2) 编译 + 烧录（PIO CLI；或 VSCode PlatformIO 的 Upload 按钮）
pio run -d docs/hardware/firmware/esp32 -t upload
# 3) 串口监视（115200）
pio device monitor -d docs/hardware/firmware/esp32
```

编译实测（2026-10-24）：ArduinoJson 7.4.3 + PubSubClient 2.8.0，RAM 15.2% / Flash 24.4%。

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
