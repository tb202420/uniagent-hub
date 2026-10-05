"""ESP32 温室灌溉节点模拟器单元测试（替代真机，研究报告 §5.8 契约）。

覆盖：
1. UniSpec 契约：3 个工具、读写标记、命令 topic、时长上限
2. 发现 + 读路径：注册后从状态缓存读取土壤湿度 / 光照强度
3. 写路径：control_pump 发布命令 → 设备回执（request_id）→ 确认成功
4. 工作流：smart_irrigation 定义（3 步 + 依赖 + 条件）

设备端实现见 adapters/mqtt_adapter/sim_esp32_greenhouse.py。
"""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import yaml

from adapters.mqtt_adapter import sim_esp32_greenhouse as sim
from adapters.mqtt_adapter.adapter import MQTTAdapter
from adapters.mqtt_adapter.topics import state_topic, command_topic
from core.contracts import CallContext
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

BROKER = "mqtt://127.0.0.1:1883"


# ---------- 1) UniSpec 契约 ----------

def test_unispec_declares_three_greenhouse_tools():
    caps = {c["name"]: c for c in sim.UNISPEC["capabilities"]}
    assert set(caps) == {"get_soil_moisture", "get_light_intensity", "control_pump"}
    assert caps["get_soil_moisture"]["readOnly"] is True
    assert caps["get_soil_moisture"]["stateField"] == "soil_moisture"
    assert caps["get_light_intensity"]["readOnly"] is True
    assert caps["get_light_intensity"]["stateField"] == "light_intensity"
    assert caps["control_pump"]["readOnly"] is False


def test_unispec_declares_command_topic_and_ids():
    assert sim.UNISPEC["id"] == "iot.irrigation_01"
    assert sim.UNISPEC["type"] == "iot_device"
    assert sim.UNISPEC["protocol"] == "mqtt"
    assert sim.UNISPEC["endpoint"]["topic"] == state_topic("irrigation_01")
    assert sim.UNISPEC["endpoint"]["command_topic"] == command_topic("irrigation_01")


def test_control_pump_duration_capped_at_600s():
    schema = next(c for c in sim.UNISPEC["capabilities"]
                  if c["name"] == "control_pump")["inputSchema"]
    assert schema["properties"]["action"]["enum"] == ["on", "off"]
    assert schema["properties"]["duration"]["maximum"] == 600
    assert schema["required"] == ["action"]


# ---------- 2/3) 发现 + 读 / 写 路径 ----------

def _adapter_with_device():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = MQTTAdapter(reg, BROKER)
    fake = mock.MagicMock()
    with mock.patch("paho.mqtt.client.Client", return_value=fake):
        adapter.start()
    spec = reg.register(sim.UNISPEC, adapter=adapter)
    return reg, adapter, fake, spec


def _msg(topic, payload):
    m = mock.MagicMock()
    m.topic = topic
    m.payload = json.dumps(payload).encode()
    return m


def test_register_then_read_soil_and_light():
    reg, adapter, _fake, spec = _adapter_with_device()
    assert spec.id == "iot.irrigation_01"
    names = {t["name"] for t in reg.list_tools()}
    assert {"get_soil_moisture", "get_light_intensity"} <= names

    adapter._on_message(None, None, _msg(state_topic("irrigation_01"),
                                         {"soil_moisture": 25.0,
                                          "light_intensity": 12000.0,
                                          "pump": "off"}))
    ctx = CallContext(trace_id="t-read", caller="test")
    soil = adapter.call_tool("get_soil_moisture", {}, ctx)
    light = adapter.call_tool("get_light_intensity", {}, ctx)
    assert soil.ok is True and soil.data == 25.0
    assert light.ok is True and light.data == 12000.0


def test_read_without_state_returns_1006():
    reg, adapter, _fake, _spec = _adapter_with_device()
    res = adapter.call_tool("get_soil_moisture", {},
                            CallContext(trace_id="t-nostate", caller="test"))
    assert res.ok is False
    assert res.error_code == 1006


def test_control_pump_publishes_and_confirms_ack():
    reg, adapter, fake, _spec = _adapter_with_device()
    adapter._on_message(None, None, _msg(state_topic("irrigation_01"),
                                         {"soil_moisture": 25.0, "pump": "off"}))

    def _deliver_ack():
        time.sleep(0.2)
        adapter._on_message(None, None, _msg(state_topic("irrigation_01"), {
            "soil_moisture": 28.0, "pump": "on", "action": "on",
            "duration": 300, "request_id": "t-pump"}))

    threading.Thread(target=_deliver_ack, daemon=True).start()
    res = adapter.call_tool("control_pump", {"action": "on", "duration": 300},
                            CallContext(trace_id="t-pump", caller="test"))
    assert res.ok is True
    assert res.data["pump"] == "on"
    assert res.data["request_id"] == "t-pump"   # 必须是本次命令的回执

    args, kwargs = fake.publish.call_args
    assert kwargs.get("qos") == 1
    assert args[0] == command_topic("irrigation_01")
    published = json.loads(args[1])
    assert published["action"] == "on"
    assert published["duration"] == 300
    assert published["request_id"] == "t-pump"


# ---------- 4) 工作流定义 ----------

def test_smart_irrigation_workflow_definition():
    doc = yaml.safe_load(
        Path("core/workflow/workflows_hardware.yaml").read_text(encoding="utf-8"))
    wf = doc["workflows"]["smart_irrigation"]
    steps = {s["id"]: s for s in wf["steps"]}
    assert set(steps) == {"s1", "s2", "s3"}
    assert steps["s1"]["tool"] == "get_soil_moisture"
    assert steps["s2"]["tool"] == "get_light_intensity"
    assert steps["s3"]["tool"] == "control_pump"
    assert steps["s3"]["args"] == {"action": "on", "duration": 300}
    assert steps["s3"]["depends_on"] == ["s1", "s2"]
    assert steps["s3"]["condition"] == "{{s1.output}} < 30"


# ---------- 5) 运行态行为（T-1 补齐：纯函数级测试）----------

def test_clamp_duration_bounds():
    assert sim.clamp_duration(None) == 600          # 缺省回退上限
    assert sim.clamp_duration("") == 600
    assert sim.clamp_duration("abc") == 600          # 非法输入回退
    assert sim.clamp_duration(0) == 1               # 下限钳位
    assert sim.clamp_duration(-5) == 1
    assert sim.clamp_duration(301) == 301           # 范围内原样
    assert sim.clamp_duration(9999) == 600          # 上限钳位（真实钳位路径）
    assert sim.clamp_duration("300") == 300         # 字符串数字


def test_apply_command_on_sets_off_deadline():
    state = {"pump": "off", "action": "off", "duration": 0, "request_id": ""}
    new, off_at = sim.apply_command(state, {"action": "on", "duration": 300,
                                            "request_id": "r1"}, 1000.0)
    assert new["pump"] == "on"
    assert new["duration"] == 300
    assert new["request_id"] == "r1"
    assert off_at == 1300.0                       # now + duration


def test_apply_command_off_clears_deadline():
    state = {"pump": "on", "action": "on", "duration": 300, "request_id": "r1"}
    new, off_at = sim.apply_command(state, {"action": "off"}, 1000.0)
    assert new["pump"] == "off"
    assert new["duration"] == 0
    assert off_at == 0.0


def test_apply_command_invalid_action_no_change():
    state = {"pump": "off", "action": "off", "duration": 0, "request_id": ""}
    new, off_at = sim.apply_command(state, {"action": "explode"}, 1000.0)
    assert new["pump"] == "off"
    assert off_at == 0.0


def test_advance_state_soil_rises_and_caps_at_100():
    state = {"soil_moisture": 98.5, "light_intensity": 1000.0,
             "pump": "on", "action": "on", "duration": 60}
    new, _ = sim.advance_state(state, now=10.0, pump_off_at=70.0)
    assert new["soil_moisture"] == 100.0           # 98.5+3 封顶 100
    assert new["pump"] == "on"                     # 未到点不停


def test_advance_state_soil_falls_floored_at_0():
    state = {"soil_moisture": 0.1, "light_intensity": 1000.0,
             "pump": "off", "action": "off", "duration": 0}
    new, _ = sim.advance_state(state, now=10.0, pump_off_at=0.0)
    assert new["soil_moisture"] == 0.0             # 0.1-0.2 下限 0


def test_advance_state_auto_stops_at_deadline():
    state = {"soil_moisture": 30.0, "light_intensity": 1000.0,
             "pump": "on", "action": "on", "duration": 60}
    new, off_at = sim.advance_state(state, now=70.0, pump_off_at=70.0)
    assert new["pump"] == "off"                    # 到点自动停泵
    assert new["duration"] == 0
    assert off_at == 0.0                           # 截止时间清零
