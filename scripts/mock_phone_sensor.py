"""手机传感器节点模拟器（硬件测试 3 的无手机预演）。

模拟 Android 手机 + IoT MQTT Panel 的行为：向注册 topic 发布 UniSpec（retain），
并周期发布状态（电量/温度）。真机测试时用手机 App 复现同样两条行为，
Hub 端零配置即可自动发现（"设备端只发布 UniSpec"的自动发现验证）。

用法：
    python -m scripts.mock_phone_sensor --broker mqtt://127.0.0.1:1883
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import time

# 规避本机 WMI 查询挂起（同 simulator.py：导入 paho 前替换 platform 内部实现）
if hasattr(platform, "_wmi_query"):
    def _no_wmi(*_a, **_k):
        raise OSError("WMI disabled for startup speed")
    platform._wmi_query = _no_wmi

import paho.mqtt.client as mqtt

from adapters.mqtt_adapter.topics import register_topic, state_topic

DEVICE_ID = "phone_01"
DEVICE_TOPIC = state_topic(DEVICE_ID)
REGISTER_TOPIC = register_topic(DEVICE_ID)

UNISPEC = {
    "id": "iot.phone_01",
    "type": "iot_device",
    "name": "手机传感器节点（模拟）",
    "protocol": "mqtt",
    "endpoint": {"broker": "MQTT_BROKER", "topic": DEVICE_TOPIC},
    "capabilities": [
        {
            "name": "get_phone_battery",
            "description": "获取手机当前电量（%）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "percent"},
            "readOnly": True,
            "stateField": "battery",
        },
        {
            "name": "get_phone_temperature",
            "description": "获取手机当前温度（摄氏度）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "celsius"},
            "readOnly": True,
            "stateField": "temperature",
        },
    ],
    "constraints": {"readOnly": True, "permissionLevel": "read",
                    "rateLimit": "10/m", "timeout": "3s"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="手机传感器节点模拟器")
    parser.add_argument("--broker", default="mqtt://broker.emqx.io:1883")
    parser.add_argument("--interval", type=float, default=5.0, help="上报间隔（秒）")
    parser.add_argument("--init-battery", type=float, default=78.0)
    args = parser.parse_args()

    import re
    m = re.match(r"^mqtt://([^:/]+)(?::(\d+))?/?$", args.broker)
    if not m:
        raise SystemExit(f"broker 格式错误: {args.broker}")
    host, port = m.group(1), int(m.group(2) or 1883)

    client = mqtt.Client(
        client_id=f"sim_phone_{random.randint(1000, 9999)}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    def on_connect(c, _ud, _flags, rc, _props):
        if rc == 0:
            spec = json.loads(json.dumps(UNISPEC).replace("MQTT_BROKER", args.broker))
            c.publish(REGISTER_TOPIC, json.dumps(spec, ensure_ascii=False), retain=True)
            print(f"[sim_phone] 已注册 UniSpec(保留) -> {REGISTER_TOPIC}")

    client.on_connect = on_connect
    client.connect_async(host, port, keepalive=20)
    client.loop_start()

    battery, temp = args.init_battery, 26.5
    try:
        while True:
            # 电量缓慢下降（均值回归式小幅波动），温度轻微抖动
            battery = max(5.0, battery - 0.2 + random.uniform(-0.3, 0.3))
            temp += (26.5 - temp) * 0.2 + random.uniform(-0.2, 0.2)
            payload = {
                "battery": round(battery, 1),
                "temperature": round(temp, 1),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            client.publish(DEVICE_TOPIC, json.dumps(payload), retain=True)
            print(f"[sim_phone] {DEVICE_TOPIC} <- {payload}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()