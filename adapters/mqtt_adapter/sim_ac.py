"""空调控制器模拟器（阶段 3 写操作闭环）。

行为：
1. 上线发布 UniSpec（retain）→ Hub 自动发现 ac_control 工具
2. 订阅命令 topic uniagent/devices/ac_01/command
3. 收到命令 → 更新本地状态 → 发布到 uniagent/devices/ac_01/state（回执）

用法：
    python -m adapters.mqtt_adapter.sim_ac --broker mqtt://broker.emqx.io:1883
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import time

# 规避本机 WMI 查询挂起（同 adapter.py）
if hasattr(platform, "_wmi_query"):
    def _no_wmi(*_a, **_k):
        raise OSError("WMI disabled for startup speed")
    platform._wmi_query = _no_wmi

import paho.mqtt.client as mqtt

from adapters.mqtt_adapter.topics import register_topic, state_topic, command_topic

STATE_TOPIC = state_topic("ac_01")
COMMAND_TOPIC = command_topic("ac_01")
REGISTER_TOPIC = register_topic("ac_01")

UNISPEC = {
    "id": "iot.ac_01",
    "type": "iot_device",
    "name": "空调控制器（模拟）",
    "protocol": "mqtt",
    "endpoint": {
        "broker": "MQTT_BROKER",
        "topic": STATE_TOPIC,
        "command_topic": COMMAND_TOPIC,
    },
    "capabilities": [
        {
            "name": "get_ac_state",
            "description": "获取空调当前状态（开关/设定温度）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "object"},
            "readOnly": True,
        },
        {
            "name": "ac_control",
            "description": "控制空调开关与设定温度（write 级）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off"]},
                    # 温度用 number（传感器算术结果为浮点；范围 16-30 仍强约束）
                    "temperature": {"type": "number", "minimum": 16, "maximum": 30},
                },
                "required": ["action"],
            },
            "outputSchema": {"type": "object"},
            "readOnly": False,
        },
    ],
    "constraints": {"readOnly": False, "permissionLevel": "write", "rateLimit": "5/m"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="空调控制器模拟器")
    parser.add_argument("--broker", default="mqtt://broker.emqx.io:1883")
    args = parser.parse_args()

    host, port = _parse_broker(args.broker)
    client = mqtt.Client(
        client_id=f"sim_ac_{random.randint(1000, 9999)}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    state = {"action": "off", "temperature": 26,
             "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def on_connect(c, _ud, _flags, rc, _props):
        if rc == 0:
            spec = json.loads(json.dumps(UNISPEC).replace("MQTT_BROKER", args.broker))
            c.publish(REGISTER_TOPIC, json.dumps(spec, ensure_ascii=False), retain=True)
            c.subscribe(COMMAND_TOPIC)
            # 上线即发布当前状态（retain）：Hub 重启/晚订阅也能立刻拿到
            # 否则 get_ac_state 在首次命令前返回 1006（修复批次实测发现）
            c.publish(STATE_TOPIC, json.dumps(state, ensure_ascii=False),
                      qos=1, retain=True)
            print(f"[sim_ac] 已注册 + 订阅 {COMMAND_TOPIC}（初始状态已发布）")

    def on_message(c, _ud, msg):
        nonlocal state
        try:
            cmd = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        action = cmd.get("action")
        if action not in ("on", "off"):
            return
        state = {
            "action": action,
            "temperature": int(cmd.get("temperature", state["temperature"])),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request_id": cmd.get("request_id", ""),
        }
        # A4 修复：命令后的状态发布必须 retain —— 否则 Hub 重启后订阅
        # 只能拿到上线时的初始 retained 状态，get_ac_state 返回陈旧值
        c.publish(STATE_TOPIC, json.dumps(state, ensure_ascii=False),
                  qos=1, retain=True)
        print(f"[sim_ac] 命令 {cmd} -> 状态 {state}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(host, port, keepalive=20)
    client.loop_start()

    try:
        while True:
            time.sleep(1)
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
