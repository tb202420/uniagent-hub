/**
 * UniAgent Hub · ESP32-S3 温室灌溉节点固件（真机轨）
 *
 * 行为契约与 Python 模拟器 adapters/mqtt_adapter/sim_esp32_greenhouse.py 严格对齐
 * （对照回归测试：tests/unit/test_firmware_contract.py）：
 *   1. 上电 → WiFi → MQTT → 向 {prefix}/register/irrigation_01 发布 retain 的
 *      UniSpec（endpoint.broker 填实际地址）→ 订阅命令 topic → 立即发布初始
 *      状态（retain）
 *   2. 周期（默认 30s）发布状态帧：soil_moisture / light_intensity / pump /
 *      action / duration / request_id / ts（真机扩展 temperature / humidity 字段）
 *   3. 命令 {action:"on"|"off", duration, request_id}：duration 非法/缺省按 600，
 *      钳位 [1,600]（对齐模拟器 clamp_duration）；执行继电器动作并立即回执
 *      状态帧（携带本次 request_id —— Hub 端 _ack_matches 以此精确匹配）
 *   4. 到达 duration 自动停泵并上报（600s 上限保护）
 *   5. WiFi/MQTT 断线指数退避重连；任务看门狗防死锁
 *
 * 已知差异（如实声明）：PubSubClient 的 publish 仅支持 QoS0；Hub 端 paho 订阅
 * 同为 QoS0，链路语义等价（模拟器侧的 qos=1 为其客户端默认）。如需 QoS1
 * 发布可后续换 espMqttClient —— 不影响当前契约。
 *
 * 硬件接线（默认引脚，按实际修改下方 PIN_* 常量）：
 *   电容土壤湿度   ADC  GPIO4  （干 ~3200mV / 湿 ~1300mV，可校准）
 *   DHT22 温湿度   DATA GPIO5  （位带直驱，无需外部库；需 4.7k 上拉）
 *   BH1750 光照    I2C  SDA=GPIO8 SCL=GPIO9（地址 0x23，连续高分辨率模式）
 *   继电器(水泵)   IN   GPIO10 （默认高电平吸合，RELAY_ACTIVE_HIGH 可改）
 *
 * 能力集：默认注册 3 能力（soil/light/pump，与模拟器及演示档"温室节点 3 工具"
 * 口径一致）；FULL_CAPABILITIES=1 追加 get_temperature/get_humidity（独立真机
 * 演示用。注意：基础档空调模拟器已占用这两个工具名，同场运行需设置
 * TOOL_PREFIX 前缀或停用空调模拟器）。
 */

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <esp_task_wdt.h>

// ========================== 用户配置区（按实际修改） ==========================
// 真实凭据放 src/secrets.h（已被 .gitignore 排除，不入库）；
// 无该文件时使用下方占位默认值 —— 便于开源用户克隆即编译。
#if __has_include("secrets.h")
#include "secrets.h"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID        "YOUR_WIFI_SSID"        // TODO: 填写 WiFi 名称
#endif
#ifndef WIFI_PASS
#define WIFI_PASS        "YOUR_WIFI_PASSWORD"    // TODO: 填写 WiFi 密码
#endif
#ifndef MQTT_HOST
#define MQTT_HOST        "192.168.1.100"         // Hub 所在网络可达的 broker（局域网=PC 内网 IP；公网可用 broker.emqx.io）
#endif
#ifndef MQTT_PORT
#define MQTT_PORT        1883                    // 明文端口（TLS 模式自动用 8883）
#endif
#define MQTT_TLS         0                       // 1 = MQTT over TLS（需在 kRootCA 粘贴完整 CA PEM）
#define MQTT_CLIENT_ID   "esp32_irrigation_01"

#define TOPIC_PREFIX     "uniagent-hub-rxyc"     // 与 Hub 默认前缀一致（HUB_TOPIC_PREFIX）
#define TOOL_PREFIX      ""                      // 工具名前缀（与空调模拟器同场时改 "gh_"）

#define FULL_CAPABILITIES 0                      // 1 = 注册 5 能力（见文件头说明）
#define ENABLE_OTA        1                      // 局域网 OTA（ArduinoOTA）

#if ENABLE_OTA
#include <ArduinoOTA.h>                          // 条件 include 必须在 ENABLE_OTA 定义之后
#endif

// 引脚（见文件头接线表）
#define PIN_SOIL_ADC   4
#define PIN_DHT_DATA   5
#define PIN_RELAY      10
#define PIN_I2C_SDA    8
#define PIN_I2C_SCL    9

// 传感器校准（电容土壤湿度：干/湿毫伏值，按实测调整）
#define SOIL_MV_DRY    3200.0f
#define SOIL_MV_WET    1300.0f
#define RELAY_ACTIVE_HIGH 1

// 行为参数（契约对齐模拟器）
#define PUBLISH_INTERVAL_MS 30000UL              // 状态上报周期（模拟器同为 30s）
#define PUMP_MAX_DURATION_S 600                  // 单次浇水上限（clamp 契约）
#define WDT_TIMEOUT_S        30

#if MQTT_TLS
// TODO: 启用 TLS 时粘贴完整根证书 PEM（broker.emqx.io:8883 使用 Let's Encrypt，
// 即 ISRG Root X1）。下方占位内容无效，务必替换后再启用 MQTT_TLS=1。
static const char kRootCA[] = R"EOF(
-----BEGIN CERTIFICATE-----
（粘贴完整 CA 证书内容）
-----END CERTIFICATE-----
)EOF";
#endif

// ================================ 主题 ======================================
static const char* kRegisterTopic = TOPIC_PREFIX "/register/irrigation_01";
static const char* kStateTopic    = TOPIC_PREFIX "/devices/irrigation_01/state";
static const char* kCommandTopic  = TOPIC_PREFIX "/devices/irrigation_01/command";

// ===================== UniSpec 模板（单块原始字符串，Python 契约测试可整块提取）====
// 占位符：MQTT_BROKER（broker 地址）/ __PREFIX__（topic 前缀）/
//         __PREFIX_TOOL__（工具名前缀）/ __TH_CAPS__（FULL 模式追加能力）
static const char kUnispecTemplate[] = R"JSONSPEC({
  "id": "iot.irrigation_01",
  "type": "iot_device",
  "name": "温室灌溉节点",
  "protocol": "mqtt",
  "endpoint": {
    "broker": "MQTT_BROKER",
    "topic": "__PREFIX__/devices/irrigation_01/state",
    "command_topic": "__PREFIX__/devices/irrigation_01/command"
  },
  "capabilities": [
    {
      "name": "__PREFIX_TOOL__get_soil_moisture",
      "description": "获取温室土壤体积含水量（%，阈值 30 以下视为需要浇水）",
      "inputSchema": {"type": "object", "properties": {}},
      "outputSchema": {"type": "number", "unit": "percent"},
      "readOnly": true,
      "stateField": "soil_moisture"
    },
    {
      "name": "__PREFIX_TOOL__get_light_intensity",
      "description": "获取温室光照强度（lux）",
      "inputSchema": {"type": "object", "properties": {}},
      "outputSchema": {"type": "number", "unit": "lux"},
      "readOnly": true,
      "stateField": "light_intensity"
    },
    {
      "name": "__PREFIX_TOOL__control_pump",
      "description": "控制灌溉水泵开关（write 级；单次时长上限 600s）",
      "inputSchema": {
        "type": "object",
        "properties": {
          "action": {"type": "string", "enum": ["on", "off"]},
          "duration": {"type": "number", "minimum": 1, "maximum": 600}
        },
        "required": ["action"]
      },
      "outputSchema": {"type": "object"},
      "readOnly": false
    }__TH_CAPS__
  ],
  "constraints": {"readOnly": false, "permissionLevel": "write",
                  "rateLimit": "5/m", "timeout": "3s"}
})JSONSPEC";

// FULL_CAPABILITIES=1 追加的 DHT22 两条能力（占位替换进 __TH_CAPS__）
static const char kThCapsJson[] =
  ",\n    {\n"
  "      \"name\": \"__PREFIX_TOOL__get_temperature\",\n"
  "      \"description\": \"获取温室空气温度（摄氏度，DHT22）\",\n"
  "      \"inputSchema\": {\"type\": \"object\", \"properties\": {}},\n"
  "      \"outputSchema\": {\"type\": \"number\", \"unit\": \"celsius\"},\n"
  "      \"readOnly\": true,\n      \"stateField\": \"temperature\"\n    },\n"
  "    {\n"
  "      \"name\": \"__PREFIX_TOOL__get_humidity\",\n"
  "      \"description\": \"获取温室空气相对湿度（%，DHT22）\",\n"
  "      \"inputSchema\": {\"type\": \"object\", \"properties\": {}},\n"
  "      \"outputSchema\": {\"type\": \"number\", \"unit\": \"percent\"},\n"
  "      \"readOnly\": true,\n      \"stateField\": \"humidity\"\n    }";

// ================================ 运行态 =====================================
static WiFiClient   g_wifiClient;
#if MQTT_TLS
static WiFiClientSecure g_secureClient;
#endif
static PubSubClient g_mqtt(g_wifiClient);

// 设备状态（字段名与模拟器状态帧一致；temperature/humidity 为真机扩展）
static float g_soil = 45.0f, g_light = 12000.0f, g_temp = NAN, g_humi = NAN;
static String g_pump = "off", g_action = "off", g_lastRequestId = "";
static int    g_duration = 0;
static unsigned long g_pumpOffAtMs = 0;      // 0 = 无自动停泵定时

static unsigned long g_lastPublishMs = 0;
static unsigned long g_wifiRetryMs = 0;
static int  g_wifiRetryDelayS = 2, g_mqttRetryDelayS = 1;   // 指数退避
static bool g_ntpStarted = false;

// ================================ 工具函数 ===================================
static void feedWdt() { esp_task_wdt_reset(); }

static String nowIso() {
  if (!g_ntpStarted) return "";
  time_t t = time(nullptr);
  if (t < 1700000000) return "";             // NTP 未同步
  struct tm tm_;
  gmtime_r(&t, &tm_);
  char buf[24];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm_);
  return String(buf);
}

// ---- DHT22 位带读取（无外部库；返回 false=校验失败/超时）----
static bool dht22Read(float* temperature, float* humidity) {
  uint8_t data[5] = {0};
  noInterrupts();
  pinMode(PIN_DHT_DATA, OUTPUT);
  digitalWrite(PIN_DHT_DATA, LOW);
  delayMicroseconds(1100);                    // 起始信号 >1ms
  digitalWrite(PIN_DHT_DATA, HIGH);
  delayMicroseconds(30);
  pinMode(PIN_DHT_DATA, INPUT_PULLUP);
  uint32_t t0 = micros();
  while (digitalRead(PIN_DHT_DATA) == HIGH) if (micros() - t0 > 100) { interrupts(); return false; }
  t0 = micros();
  while (digitalRead(PIN_DHT_DATA) == LOW)  if (micros() - t0 > 100) { interrupts(); return false; }
  t0 = micros();
  while (digitalRead(PIN_DHT_DATA) == HIGH) if (micros() - t0 > 100) { interrupts(); return false; }
  for (int i = 0; i < 40; i++) {              // 40 位：50us 低 + 26~70us 高（长=1）
    t0 = micros();
    while (digitalRead(PIN_DHT_DATA) == LOW)  if (micros() - t0 > 80)  { interrupts(); return false; }
    t0 = micros();
    while (digitalRead(PIN_DHT_DATA) == HIGH) if (micros() - t0 > 100) { interrupts(); return false; }
    if (micros() - t0 > 45) data[i / 8] |= (0x80 >> (i % 8));
  }
  interrupts();
  if ((uint8_t)(data[0] + data[1] + data[2] + data[3]) != data[4]) return false;
  *humidity = (data[0] * 256 + data[1]) * 0.1f;
  int raw = (data[2] & 0x7F) * 256 + data[3];
  if (data[2] & 0x80) raw = -raw;
  *temperature = raw * 0.1f;
  return true;
}

// ---- BH1750（连续高分辨率模式，地址 0x23）----
static bool bh1750Read(float* lux) {
  Wire.beginTransmission(0x23);
  Wire.write(0x10);
  if (Wire.endTransmission() != 0) return false;
  delay(180);                                 // 首次测量 120ms+
  if (Wire.requestFrom((uint8_t)0x23, (uint8_t)2) != 2) return false;
  uint16_t raw = ((uint16_t)Wire.read() << 8) | (uint16_t)Wire.read();
  *lux = raw / 1.2f;
  return true;
}

// ---- 土壤湿度（电容 ADC → 体积含水量 %，8 次均值）----
static float soilReadPercent() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) { mv += analogReadMilliVolts(PIN_SOIL_ADC); delay(2); }
  mv /= 8;
  float pct = (SOIL_MV_DRY - (float)mv) / (SOIL_MV_DRY - SOIL_MV_WET) * 100.0f;
  return constrain(pct, 0.0f, 100.0f);
}

static void relayWrite(bool on) {
#if RELAY_ACTIVE_HIGH
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
#else
  digitalWrite(PIN_RELAY, on ? LOW : HIGH);
#endif
}

// ================================ MQTT =======================================
static void publishState(bool retain) {
  JsonDocument doc;
  doc["soil_moisture"]   = roundf(g_soil * 10) / 10.0;
  doc["light_intensity"] = roundf(g_light * 10) / 10.0;
  if (!isnan(g_temp))  doc["temperature"] = roundf(g_temp * 10) / 10.0;
  if (!isnan(g_humi))  doc["humidity"]    = roundf(g_humi * 10) / 10.0;
  doc["pump"] = g_pump;
  doc["action"] = g_action;
  doc["duration"] = g_duration;
  doc["request_id"] = g_lastRequestId;
  String ts = nowIso();
  if (ts.length()) doc["ts"] = ts;
  String out;
  serializeJson(doc, out);
  g_mqtt.publish(kStateTopic, out.c_str(), retain);
}

// duration 归一化（对齐模拟器 clamp_duration：非法/缺省 → 600，钳位 [1,600]）
static int clampDuration(JsonVariant v) {
  if (v.isNull() || v.is<const char*>()) return PUMP_MAX_DURATION_S;
  if (!v.is<int>() && !v.is<float>() && !v.is<double>()) return PUMP_MAX_DURATION_S;
  int d = (int)v.as<float>();
  if (d < 1) d = 1;
  if (d > PUMP_MAX_DURATION_S) d = PUMP_MAX_DURATION_S;
  return d;
}

static void onCommand(char* topic, byte* payload, unsigned int length) {
  JsonDocument cmd;
  if (deserializeJson(cmd, payload, length)) return;        // 解析失败忽略
  const char* action = cmd["action"] | "";
  if (strcmp(action, "on") != 0 && strcmp(action, "off") != 0) return;
  g_lastRequestId = String(cmd["request_id"] | "");
  if (strcmp(action, "on") == 0) {
    g_duration = clampDuration(cmd["duration"]);
    g_pumpOffAtMs = millis() + (unsigned long)g_duration * 1000UL;
    relayWrite(true);
  } else {
    g_duration = 0;
    g_pumpOffAtMs = 0;
    relayWrite(false);
  }
  g_pump = String(action);
  g_action = String(action);
  publishState(false);                                       // 立即回执（带 request_id）
  Serial.printf("[esp32_irrigation] 命令 %s -> 水泵 %s（%ds）\n",
                g_lastRequestId.c_str(), action, g_duration);
}

static void registerAndSubscribe() {
  String spec(kUnispecTemplate);
#if FULL_CAPABILITIES
  spec.replace("__TH_CAPS__", kThCapsJson);
#else
  spec.replace("__TH_CAPS__", "");
#endif
  String port = MQTT_TLS ? String(8883) : String(MQTT_PORT);
  spec.replace("MQTT_BROKER", String(MQTT_HOST) + ":" + port);
  spec.replace("__PREFIX__", TOPIC_PREFIX);
  spec.replace("__PREFIX_TOOL__", TOOL_PREFIX);

  bool ok = g_mqtt.publish(kRegisterTopic, spec.c_str(), true);   // retain（契约）
  Serial.printf("[esp32_irrigation] UniSpec 注册(%s) -> %s\n",
                ok ? "retain,ok" : "失败", kRegisterTopic);
  g_mqtt.subscribe(kCommandTopic);
  Serial.printf("[esp32_irrigation] 已订阅 %s\n", kCommandTopic);
  publishState(true);                                             // 初始状态 retain（契约）
}

static bool connectMqtt() {
#if MQTT_TLS
  g_secureClient.setCACert(kRootCA);
  g_mqtt.setClient(g_secureClient);
  g_mqtt.setServer(MQTT_HOST, 8883);
#else
  g_mqtt.setClient(g_wifiClient);
  g_mqtt.setServer(MQTT_HOST, MQTT_PORT);
#endif
  if (g_mqtt.connect(MQTT_CLIENT_ID)) {
    g_mqttRetryDelayS = 1;
    Serial.print("[esp32_irrigation] MQTT 已连接 ");
    Serial.println(MQTT_HOST);
    registerAndSubscribe();
    return true;
  }
  Serial.printf("[esp32_irrigation] MQTT 连接失败 rc=%d，%ds 后重试\n",
                (int)g_mqtt.state(), g_mqttRetryDelayS);
  unsigned long until = millis() + (unsigned long)g_mqttRetryDelayS * 1000UL;
  while (millis() < until) { feedWdt(); delay(100); }
  g_mqttRetryDelayS = (g_mqttRetryDelayS * 2 > 30) ? 30 : g_mqttRetryDelayS * 2;
  return false;
}

// ================================ 主流程 =====================================
void setup() {
  Serial.begin(115200);
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
  (void)esp_task_wdt_add(nullptr);           // loopTask 已被监视时忽略返回值

  pinMode(PIN_RELAY, OUTPUT);
  relayWrite(false);
  analogReadResolution(12);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[esp32_irrigation] 连接 WiFi ");
  Serial.println(WIFI_SSID);

  g_mqtt.setCallback(onCommand);
  g_mqtt.setBufferSize(2560);                // UniSpec JSON ~1.6KB，默认 256B 不够
  g_mqtt.setKeepAlive(30);                   // 与模拟器/适配器一致

#if ENABLE_OTA
  ArduinoOTA.begin();
#endif
}

void loop() {
  feedWdt();
#if ENABLE_OTA
  ArduinoOTA.handle();
#endif

  // WiFi 断线重连（指数退避）
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - g_wifiRetryMs > (unsigned long)g_wifiRetryDelayS * 1000UL) {
      Serial.println("[esp32_irrigation] WiFi 断线，重连…");
      WiFi.disconnect();
      WiFi.reconnect();
      g_wifiRetryMs = millis();
      g_wifiRetryDelayS = (g_wifiRetryDelayS * 2 > 30) ? 30 : g_wifiRetryDelayS * 2;
    }
    delay(100);
    return;
  }
  g_wifiRetryDelayS = 2;
  if (!g_ntpStarted) {
    configTime(0, 0, "pool.ntp.org", "ntp.aliyun.com");  // UTC（ts 字段带 Z）
    g_ntpStarted = true;                                 // 未同步时 ts 留空，不阻塞
  }

  // MQTT 保活 / 断线重连
  if (!g_mqtt.connected()) {
    if (!connectMqtt()) { delay(100); return; }
  }
  g_mqtt.loop();

  // 传感器采样
  float t, h, lux;
  if (dht22Read(&t, &h)) { g_temp = t; g_humi = h; }
  if (bh1750Read(&lux)) g_light = lux;
  g_soil = soilReadPercent();

  // 到点自动停泵（时长上限保护，契约）
  if (g_pump == "on" && g_pumpOffAtMs != 0 && (long)(millis() - g_pumpOffAtMs) >= 0) {
    relayWrite(false);
    g_pump = "off"; g_action = "off"; g_duration = 0; g_pumpOffAtMs = 0;
    publishState(false);
    Serial.println("[esp32_irrigation] 达到设定时长，水泵自动停止");
  }

  // 周期状态上报
  if (millis() - g_lastPublishMs >= PUBLISH_INTERVAL_MS) {
    g_lastPublishMs = millis();
    publishState(false);
    Serial.printf("[esp32_irrigation] %s <- soil=%.1f%% light=%.0flux pump=%s\n",
                  kStateTopic, g_soil, g_light, g_pump.c_str());
  }
  delay(50);
}
