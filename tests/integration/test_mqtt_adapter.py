"""MQTT 适配器集成测试（Mock broker 驱动回调，不依赖真实 broker）。

覆盖：UniSpec 自动发现注册 → 状态缓存 → get_temperature 调用 → 离线降级。
真实 broker（EMQX/amqtt）E2E 在阶段 2 验证。
"""

import json
import threading
import types
from unittest import mock

# 规避本机 WMI 查询挂起（与 adapters.mqtt_adapter 相同的兼容性处理，
# 否则 mock.patch("paho.mqtt.client.Client") 触发导入会挂起数秒~数十秒）
import platform
if hasattr(platform, "_wmi_query"):
    def _no_wmi(*_a, **_k):
        raise OSError("WMI disabled for tests")
    platform._wmi_query = _no_wmi

from core.contracts import CallContext
from core.registry.registry import ToolRegistry
from adapters.mqtt_adapter.adapter import MQTTAdapter
from adapters.mqtt_adapter.topics import register_topic, state_topic

BROKER = "mqtt://127.0.0.1:1883"


def _fake_paho_client():
    """构造假的 paho client：记录订阅、直接驱动 on_message 回调。"""
    client = mock.MagicMock()
    client.on_message = None
    client.loop_start = mock.MagicMock()
    return client


def _msg(topic: str, payload: str):
    m = mock.MagicMock()
    m.topic = topic
    m.payload = payload.encode()
    return m


def _make_adapter():
    reg = ToolRegistry()
    adapter = MQTTAdapter(reg, BROKER)
    fake = _fake_paho_client()
    with mock.patch("paho.mqtt.client.Client", return_value=fake):
        adapter.start()
    assert adapter._client is not None
    return reg, adapter, fake


def test_device_autodiscovery_and_get_temperature():
    reg, adapter, fake = _make_adapter()

    # 模拟设备上线：发布 UniSpec 到 {prefix}/register/temp_01
    spec = {
        "id": "iot.temp_01",
        "type": "iot_device",
        "name": "客厅温度传感器（模拟）",
        "protocol": "mqtt",
        "endpoint": {"broker": BROKER, "topic": state_topic("temp_01")},
        "capabilities": [{
            "name": "get_temperature",
            "description": "获取客厅当前温度（摄氏度）",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {"type": "number", "unit": "celsius"},
            "readOnly": True,
            "stateField": "temperature",
        }],
        "constraints": {"readOnly": True, "permissionLevel": "read"},
    }
    adapter._on_message(fake, None, _msg(register_topic("temp_01"), json.dumps(spec)))

    # 自动发现注册成功
    assert reg.get("iot.temp_01") is not None
    tools = {t["name"] for t in reg.list_tools()}
    assert "get_temperature" in tools

    # 模拟状态上报
    state = {"temperature": 26.5, "humidity": 60}
    adapter._on_message(fake, None,
                        _msg(state_topic("temp_01"), json.dumps(state)))

    # Agent 调用 get_temperature
    res = adapter.call_tool("get_temperature", {}, CallContext(trace_id="t1", caller="test"))
    assert res.ok is True
    assert res.data == 26.5


def test_device_offline_returns_1006():
    reg, adapter, _ = _make_adapter()
    spec = {
        "id": "iot.temp_02",
        "type": "iot_device",
        "name": "离线传感器",
        "protocol": "mqtt",
        "endpoint": {"broker": BROKER, "topic": state_topic("temp_02")},
        "capabilities": [{
            "name": "get_temperature",
            "description": "d",
            "inputSchema": {"type": "object", "properties": {}},
            "readOnly": True,
            "stateField": "temperature",
        }],
    }
    adapter._on_message(None, None, _msg(register_topic("temp_02"), json.dumps(spec)))
    # 无状态上报 → 资源不可用
    res = adapter.call_tool("get_temperature", {}, CallContext(trace_id="t2", caller="test"))
    assert res.ok is False
    assert res.error_code == 1006


def test_invalid_unispec_rejected():
    reg, adapter, _ = _make_adapter()
    bad = {"id": "Bad", "type": "iot_device", "protocol": "http",
           "name": "x", "capabilities": []}
    adapter._on_message(None, None, _msg(register_topic("bad"), json.dumps(bad)))
    assert reg.get("Bad") is None
