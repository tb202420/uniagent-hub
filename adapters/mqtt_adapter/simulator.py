"""MQTT 设备模拟器（Python 模拟 ESP32，比赛降级方案核心组件）。

行为：
1. 上线时向 uniagent/register/<device_id> 发布 UniSpec（设备自动发现）
2. 周期向设备状态 topic 发布 JSON 状态（温度/湿度轻微波动）
3. 可选 --go-offline：一段时间后停止上报（演示资源不可用降级）

用法：
    python -m adapters.mqtt_adapter.simulator --broker mqtt://127.0.0.1:1883
"""

from __future__ import annotations

import argparse
import json
import random
import time

# 规避本机 WMI 查询挂起（同 adapter.py，见 start() 注释）
import platform
if hasattr(platform, "_wmi_query"):
    def _no_wmi(*_a, **_k):
        raise OSError("WMI disabled for startup speed")
    platform._wmi_query = _no_wmi

import paho.mqtt.client as mqtt

from adapters.mqtt_adapter.topics import register_topic, state_topic

DEVICE_TOPIC = state_topic("temp_01")
REGISTER_TOPIC = register_topic("temp_01")

UNISPEC = {
    "id": "iot.temp_01",
    "type": "iot_device",
    "name": "客厅温度传感器（模拟）",
    "protocol": "mqtt",
    "endpoint": {"broker": "MQTT_BROKER", "topic": DEVICE_TOPIC},
    "capabilities": [
        {
            "name": "get_temperature",
            "description": "获取客厅当前温度（摄氏度）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "celsius"},
            "readOnly": True,
            "stateField": "temperature",
        },
        {
            "name": "get_humidity",
            "description": "获取客厅当前湿度（%）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "percent"},
            "readOnly": True,
            "stateField": "humidity",
        },
    ],
    "constraints": {"readOnly": True, "permissionLevel": "read",
                    "rateLimit": "1/s", "timeout": "3s"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT 设备模拟器")
    parser.add_argument("--broker", default="mqtt://broker.emqx.io:1883",
                        help="MQTT Broker（公共 broker 便于无 Docker 联调）")
    parser.add_argument("--interval", type=float, default=2.0, help="状态上报间隔（秒）")
    parser.add_argument("--init-temp", type=float, default=25.5,
                        help="初始温度（演示用可设 30 触发工作流条件）")
    parser.add_argument("--go-offline-after", type=float, default=0,
                        help="N 秒后停止上报（模拟设备掉线，0=不停止）")
    args = parser.parse_args()

    host, port = _parse_broker(args.broker)
    # 唯一 client_id（公共 broker 同名连接会互相踢下线）；新版回调 API
    client = mqtt.Client(
        client_id=f"sim_temp_{random.randint(1000, 9999)}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    def on_connect(c, _ud, _flags, rc, _props):
        if rc == 0:
            # 连接建立后发布 UniSpec 注册（retain=True：broker 保留该消息，
            # 后到的订阅者（如 Hub）也能收到 → 自动发现不丢失）
            spec = json.loads(json.dumps(UNISPEC).replace("MQTT_BROKER", args.broker))
            c.publish(REGISTER_TOPIC, json.dumps(spec, ensure_ascii=False), retain=True)
            print(f"[simulator] 已注册 UniSpec(保留) -> {REGISTER_TOPIC}")

    client.on_connect = on_connect
    client.connect_async(host, port, keepalive=10)
    client.loop_start()

    temp, humid = args.init_temp, 55.0
    start = time.time()
    try:
        while True:
            # 均值回归波动（而非随机游走）：温度始终围绕初始值小幅震荡。
            # 随机游走会无界漂移（实测漂到 36°C，导致工作流算出 34 > 空调
            # 上限 30 而失败）；回归模型也更贴近真实房间热惯性（ERR-11）
            temp += (args.init_temp - temp) * 0.2 + random.uniform(-0.3, 0.3)
            humid += (55.0 - humid) * 0.2 + random.uniform(-1.0, 1.0)
            payload = {
                "temperature": round(max(15.0, min(38.0, temp)), 1),
                "humidity": round(max(20.0, min(90.0, humid)), 1),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            # A4 修复：状态上报带 retain —— Hub 重启/晚订阅即可拿到最新状态，
            # 不依赖设备下一轮上报（修复批次 A4：与 sim_ac 状态发布保持一致）
            client.publish(DEVICE_TOPIC, json.dumps(payload), retain=True)
            print(f"[simulator] {DEVICE_TOPIC} <- {payload}")
            if args.go_offline_after and time.time() - start > args.go_offline_after:
                print("[simulator] 设备进入离线状态（停止上报）")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


def _parse_broker(broker: str) -> tuple[str, int]:
    import re
    m = re.match(r"^mqtt://([^:/]+)(?::(\d+))?/?$", broker)
    if not m:
        raise SystemExit(f"broker 格式错误: {broker}")
    return m.group(1), int(m.group(2) or 1883)


if __name__ == "__main__":
    main()
