"""MQTT 写操作（ac_control）单元测试（mock paho client）+ Gateway 权限优先级测试。

权限模型（ERR-03 修复，UniSpec v0.2.0）：
  required = cap.permissionLevel > (cap.readOnly ? "read" : spec.constraints.permissionLevel)
"""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from core.contracts import CallContext
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from adapters.mqtt_adapter.adapter import MQTTAdapter
from adapters.mqtt_adapter.topics import state_topic, command_topic

BROKER = "mqtt://127.0.0.1:1883"

AC_SPEC = {
    "id": "iot.ac_01",
    "type": "iot_device",
    "name": "空调",
    "protocol": "mqtt",
    "endpoint": {"broker": BROKER, "topic": state_topic("ac_01"),
                 "command_topic": command_topic("ac_01")},
    "capabilities": [
        {
            "name": "get_ac_state",
            "description": "查询空调状态",
            "inputSchema": {"type": "object", "properties": {}},
            "readOnly": True,
            "stateField": None,
        },
        {
            "name": "ac_control",
            "description": "控制空调",
            "inputSchema": {"type": "object",
                            "properties": {"action": {"type": "string", "enum": ["on", "off"]}},
                            "required": ["action"]},
            "readOnly": False,
        },
    ],
    "constraints": {"readOnly": False, "permissionLevel": "write"},
}


def _adapter():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = MQTTAdapter(reg, BROKER)
    fake = mock.MagicMock()
    with mock.patch("paho.mqtt.client.Client", return_value=fake):
        adapter.start()
    spec = reg.register(AC_SPEC, adapter=adapter)
    return reg, adapter, fake, spec


def _msg(topic, payload):
    m = mock.MagicMock()
    m.topic = topic
    m.payload = json.dumps(payload).encode()
    return m


def test_ac_control_publishes_command_and_waits_ack():
    reg, adapter, fake, spec = _adapter()
    state = {"action": "on", "temperature": 26}
    adapter._states[state_topic("ac_01")] = {"action": "off"}
    # 回执在 0.2s 内到达

    def _deliver_ack():
        time.sleep(0.2)
        adapter._on_message(fake, None,
                            _msg(state_topic("ac_01"), state))

    threading.Thread(target=_deliver_ack, daemon=True).start()
    res = adapter.call_tool("ac_control", {"action": "on"},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is True
    assert res.data == state
    fake.publish.assert_called_once()
    args, kwargs = fake.publish.call_args
    assert kwargs.get("qos") == 1
    published = json.loads(args[1])  # publish(topic, payload, qos=1)
    assert published["action"] == "on"


def test_ac_control_timeout_returns_sent_ack():
    reg, adapter, fake, spec = _adapter()
    adapter._states[state_topic("ac_01")] = {"action": "off"}
    res = adapter.call_tool("ac_control", {"action": "on"},
                            CallContext(trace_id="t2", caller="test"))
    assert res.ok is True  # 不阻塞：命令已发送，状态未确认
    assert res.data["status"] == "命令已发送，状态未确认"


def test_ac_control_stale_ack_ignored_and_new_ack_used():
    """回归：缓存状态已是目标 action（上次命令残留）时，不得立即返回陈旧回执。

    修复前 `_call_write` 只比对 action，连续两次 ac_control(on) 的第二次会
    0ms 返回上一次的状态（旧 request_id / 旧设定温度），即"未确认本次命令却报成功"。
    """
    reg, adapter, fake, spec = _adapter()
    adapter._states[state_topic("ac_01")] = {
        "action": "on", "temperature": 26, "request_id": "old-cmd"}

    def _deliver_new_ack():
        time.sleep(0.2)
        adapter._on_message(fake, None, _msg(state_topic("ac_01"), {
            "action": "on", "temperature": 28, "request_id": "t-new"}))

    threading.Thread(target=_deliver_new_ack, daemon=True).start()
    res = adapter.call_tool("ac_control", {"action": "on", "temperature": 28},
                            CallContext(trace_id="t-new", caller="test"))
    assert res.ok is True
    assert res.data["request_id"] == "t-new"      # 必须是本次命令的回执
    assert res.data["temperature"] == 28          # 而非残留的 26


def test_ac_control_only_stale_ack_times_out():
    """缓存只有旧 request_id 的回执 → 本次命令未获确认，走"已发送未确认"分支。"""
    reg, adapter, fake, spec = _adapter()
    adapter._states[state_topic("ac_01")] = {
        "action": "on", "temperature": 26, "request_id": "old-cmd"}
    res = adapter.call_tool("ac_control", {"action": "on"},
                            CallContext(trace_id="t-new2", caller="test"))
    assert res.ok is True
    assert res.data["status"] == "命令已发送，状态未确认"


def test_ac_control_device_without_request_id_still_acks():
    """兼容性：设备不回声 request_id 时退化为 action 匹配（旧设备不受影响）。"""
    reg, adapter, fake, spec = _adapter()

    def _deliver_ack():
        time.sleep(0.2)
        adapter._on_message(fake, None, _msg(state_topic("ac_01"),
                                             {"action": "on", "temperature": 26}))

    threading.Thread(target=_deliver_ack, daemon=True).start()
    res = adapter.call_tool("ac_control", {"action": "on"},
                            CallContext(trace_id="t-legacy", caller="test"))
    assert res.ok is True
    assert res.data["action"] == "on"


def test_ac_control_missing_command_topic():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = MQTTAdapter(reg, BROKER)
    fake = mock.MagicMock()
    with mock.patch("paho.mqtt.client.Client", return_value=fake):
        adapter.start()
    spec = dict(AC_SPEC)
    spec["endpoint"] = {"broker": BROKER, "topic": "x/state"}  # 无 command_topic
    reg.register(spec, adapter=adapter)
    res = adapter.call_tool("ac_control", {"action": "on"},
                            CallContext(trace_id="t3", caller="test"))
    assert res.ok is False
    assert res.error_code == 1006


# ---- Gateway 层权限优先级（ERR-03 修复回归）----

def _gateway_with_ac():
    """Registry + MQTTAdapter(mock) + MCPGateway，预填空调状态。"""
    reg, adapter, fake, _ = _adapter()
    adapter._states[state_topic("ac_01")] = {"action": "off", "temperature": 27}
    gw = MCPGateway(reg, AuditLogger(AuditStore(max_memory=100)))
    return gw


def test_gateway_get_ac_state_read_permission_ok():
    """readOnly 能力自动降为 read：read 权限可查询空调状态（ERR-03 修复前误 1003）。"""
    gw = _gateway_with_ac()
    res = gw.call({"name": "get_ac_state", "arguments": {},
                   "permission_level": "read", "caller": "perm-test-1"})
    assert res["isError"] is False
    # 未声明 stateField 且状态中无 "ac_state" 键 → 返回完整状态对象
    assert res["content"][0]["text"].find("off") >= 0 or "off" in json.dumps(res)


def test_gateway_ac_control_read_permission_denied():
    """写能力沿用资源级 permissionLevel=write：read 权限调用 ac_control 应 1003。"""
    gw = _gateway_with_ac()
    res = gw.call({"name": "ac_control", "arguments": {"action": "on"},
                   "permission_level": "read", "caller": "perm-test-2"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1003


def test_gateway_ac_control_write_permission_ok():
    """write 权限调用 ac_control 放行（命令已发布即视为成功）。"""
    gw = _gateway_with_ac()
    res = gw.call({"name": "ac_control", "arguments": {"action": "on"},
                   "permission_level": "write", "caller": "perm-test-3"})
    assert res["isError"] is False


def test_gateway_capability_permission_level_override():
    """cap.permissionLevel 显式覆盖优先：readOnly 查询能力要求 write（门锁加固场景）。"""
    reg, adapter, fake, _ = _adapter()
    hardened = json.loads(json.dumps(AC_SPEC))
    hardened["id"] = "iot.lock_01"
    hardened["endpoint"] = {"broker": BROKER, "topic": state_topic("lock_01")}
    hardened["capabilities"] = [{
        "name": "get_lock_state",
        "description": "查询门锁状态（敏感设备，要求 write 级授权）",
        "inputSchema": {"type": "object", "properties": {}},
        "readOnly": True,
        "permissionLevel": "write",
    }]
    reg.register(hardened, adapter=adapter)
    adapter._states[state_topic("lock_01")] = {"locked": True}
    gw = MCPGateway(reg, AuditLogger(AuditStore(max_memory=100)))

    # read 权限被拒（cap.permissionLevel=write 优先于 readOnly）
    res = gw.call({"name": "get_lock_state", "arguments": {},
                   "permission_level": "read", "caller": "perm-test-4"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1003

    # write 权限放行
    res = gw.call({"name": "get_lock_state", "arguments": {},
                   "permission_level": "write", "caller": "perm-test-4"})
    assert res["isError"] is False
