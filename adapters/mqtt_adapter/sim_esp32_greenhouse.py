"""ESP32 温室灌溉节点模拟器（Python MQTT 模拟，替代真实硬件）。

对齐研究报告 §5.8 的设备行为契约：
1. 上线向 {prefix}/register/irrigation_01 发布 UniSpec（retain）→ Hub 自动发现
2. 周期（默认 30s）向状态 topic 发布 JSON：土壤湿度 / 光照强度 / 水泵状态
3. 订阅命令 topic，收到 control_pump 命令 → 更新水泵状态并发布回执（QoS1，带 request_id）
4. 浇水后土壤湿度上升、停泵后缓慢下降（复现真机"浇水后读数爬升"的物理行为）
5. 水泵单次运行时长上限 600s，到点自动停泵并上报

对外暴露 3 个 MCP 工具（与硬件档"ESP32 温室 3"一致）：
    get_soil_moisture / get_light_intensity / control_pump

用法：
    python -m adapters.mqtt_adapter.sim_esp32_greenhouse --broker mqtt://127.0.0.1:1883
    python -m adapters.mqtt_adapter.sim_esp32_greenhouse --init-soil 25   # 演示用：干土触发浇水
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import time
from typing import Any

# 规避本机 WMI 查询挂起（同 adapter.py / simulator.py）
if hasattr(platform, "_wmi_query"):
    def _no_wmi(*_a, **_k):
        raise OSError("WMI disabled for startup speed")
    platform._wmi_query = _no_wmi

import paho.mqtt.client as mqtt

from adapters.mqtt_adapter.topics import register_topic, state_topic, command_topic

DEVICE_ID = "irrigation_01"
STATE_TOPIC = state_topic(DEVICE_ID)
COMMAND_TOPIC = command_topic(DEVICE_ID)
REGISTER_TOPIC = register_topic(DEVICE_ID)

PUMP_MAX_DURATION_S = 600


# ---- 纯函数（运行态行为契约，供单元测试与主循环共用）----

def clamp_duration(duration: Any) -> int:
    """把 control_pump 的 duration 归一化到 [1, 600]；非法/缺省回退 600。"""
    if duration in (None, ""):
        return PUMP_MAX_DURATION_S
    try:
        value = int(duration)
    except (TypeError, ValueError):
        return PUMP_MAX_DURATION_S
    return max(1, min(PUMP_MAX_DURATION_S, value))


def apply_command(state: dict, command: dict, now: float) -> tuple[dict, float]:
    """把一条 control_pump 命令应用到设备状态。

    返回 (新状态, 自动停泵截止时间)。action 非法时状态不变化。
    """
    action = command.get("action")
    if action not in ("on", "off"):
        return {**state}, 0.0
    duration = clamp_duration(command.get("duration")) if action == "on" else 0
    pump_off_at = (now + duration) if action == "on" else 0.0
    new_state = {**state,
                 "pump": action,
                 "action": action,
                 "duration": duration,
                 "request_id": command.get("request_id", "")}
    return new_state, pump_off_at


def advance_state(state: dict, now: float, pump_off_at: float) -> tuple[dict, float]:
    """推进一个采样周期：土壤湿度动态 + 光照微扰 + 到点自动停泵。"""
    new_state = {**state}
    # 物理行为：开泵时土壤湿度上升（浇水），停泵时缓慢下降（蒸发）
    if new_state.get("pump") == "on":
        new_state["soil_moisture"] = round(
            min(100.0, new_state["soil_moisture"] + 3.0), 1)
    else:
        new_state["soil_moisture"] = round(
            max(0.0, new_state["soil_moisture"] - 0.2), 1)
    new_state["light_intensity"] = round(
        max(0.0, new_state["light_intensity"] + random.uniform(-200, 200)), 1)
    # 到点自动停泵（复现真机时长上限保护）
    if new_state.get("pump") == "on" and pump_off_at and now >= pump_off_at:
        new_state.update({"pump": "off", "action": "off", "duration": 0})
        pump_off_at = 0.0
    return new_state, pump_off_at

UNISPEC = {
    "id": "iot.irrigation_01",
    "type": "iot_device",
    "name": "温室灌溉节点（模拟）",
    "protocol": "mqtt",
    "endpoint": {
        "broker": "MQTT_BROKER",
        "topic": STATE_TOPIC,
        "command_topic": COMMAND_TOPIC,
    },
    "capabilities": [
        {
            "name": "get_soil_moisture",
            "description": "获取温室土壤体积含水量（%，阈值 30 以下视为需要浇水）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "percent"},
            "readOnly": True,
            "stateField": "soil_moisture",
        },
        {
            "name": "get_light_intensity",
            "description": "获取温室光照强度（lux）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "lux"},
            "readOnly": True,
            "stateField": "light_intensity",
        },
        {
            "name": "control_pump",
            "description": "控制灌溉水泵开关（write 级；单次时长上限 600s）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off"]},
                    "duration": {"type": "number", "minimum": 1,
                                 "maximum": PUMP_MAX_DURATION_S},
                },
                "required": ["action"],
            },
            "outputSchema": {"type": "object"},
            "readOnly": False,
        },
    ],
    "constraints": {"readOnly": False, "permissionLevel": "write",
                    "rateLimit": "5/m", "timeout": "3s"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="ESP32 温室灌溉节点模拟器")
    parser.add_argument("--broker", default="mqtt://broker.emqx.io:1883",
                        help="MQTT Broker（公共 broker 便于无 Docker 联调）")
    parser.add_argument("--interval", type=float, default=30.0,
                        help="状态上报间隔（秒），对齐真机 30s 采集周期")
    parser.add_argument("--init-soil", type=float, default=45.0,
                        help="初始土壤湿度（%%）；演示可设 25 触发浇水条件")
    parser.add_argument("--init-light", type=float, default=12000.0,
                        help="初始光照强度（lux）")
    args = parser.parse_args()

    host, port = _parse_broker(args.broker)
    client = mqtt.Client(
        client_id=f"sim_irrigation_{random.randint(1000, 9999)}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    state = {
        "soil_moisture": round(max(0.0, min(100.0, args.init_soil)), 1),
        "light_intensity": round(args.init_light, 1),
        "pump": "off",
        "action": "off",
        "duration": 0,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    pump_off_at = 0.0  # 定时停泵截止时间（epoch 秒）

    def snapshot() -> dict:
        return {**state,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def on_connect(c, _ud, _flags, rc, _props):
        if rc == 0:
            spec = json.loads(json.dumps(UNISPEC).replace("MQTT_BROKER", args.broker))
            c.publish(REGISTER_TOPIC, json.dumps(spec, ensure_ascii=False), retain=True)
            c.subscribe(COMMAND_TOPIC)
            # 上线即发布初始状态（retain + qos1）：Hub 晚订阅/重启也能立即读到，
            # 否则首次读取会返回 1006（无最新状态）
            c.publish(STATE_TOPIC, json.dumps(snapshot(), ensure_ascii=False),
                      qos=1, retain=True)
            print(f"[sim_irrigation] 已注册 UniSpec(保留) -> {REGISTER_TOPIC}")
            print(f"[sim_irrigation] 已订阅 {COMMAND_TOPIC}（初始状态已发布）")
        else:
            print(f"[sim_irrigation] 连接失败 rc={rc}")

    def on_message(c, _ud, msg):
        nonlocal pump_off_at
        try:
            cmd = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return
        new_state, new_off_at = apply_command(state, cmd, time.time())
        state.update(new_state)
        pump_off_at = new_off_at
        # 回执（qos=1）：adapter._call_write 用 request_id 精确匹配本次命令
        c.publish(STATE_TOPIC, json.dumps(snapshot(), ensure_ascii=False), qos=1)
        print(f"[sim_irrigation] 命令 {cmd} -> 水泵 {state['action']}"
              + (f"（{state['duration']}s 后自动停止）" if state["action"] == "on" else ""))

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(host, port, keepalive=30)
    client.loop_start()

    try:
        while True:
            new_state, pump_off_at = advance_state(state, time.time(), pump_off_at)
            auto_stopped = (state.get("pump") == "on"
                            and new_state.get("pump") == "off")
            state.update(new_state)
            if auto_stopped:
                client.publish(STATE_TOPIC,
                               json.dumps(snapshot(), ensure_ascii=False), qos=1)
                print("[sim_irrigation] 达到设定时长，水泵自动停止")
            client.publish(STATE_TOPIC, json.dumps(snapshot(), ensure_ascii=False))
            print(f"[sim_irrigation] {STATE_TOPIC} <- {snapshot()}")
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
