"""v3.0 网关 API 集成测试：事件 WS / HITL 审批 / 追踪 / 终端 token / A2A。"""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.contracts import ToolResult
from core.gateway.event_bus import EventBus
from core.gateway.server import MCPGateway, create_app
from core.guard.audit import AuditLogger, AuditStore
from core.guard.hitl import ApprovalBroker
from core.observability.tracer import Tracer
from core.registry.registry import ToolRegistry
from core.terminal.tokens import TerminalTokenRegistry

SPEC = {
    "id": "iot.testnode",
    "type": "iot_device",
    "name": "测试节点",
    "protocol": "mqtt",
    "capabilities": [
        {"name": "get_state", "description": "读取状态", "readOnly": True,
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "control_pump", "description": "控制水泵", "readOnly": False,
         "inputSchema": {"type": "object", "properties": {
             "action": {"type": "string", "enum": ["on", "off"]},
             "duration": {"type": "number", "minimum": 1, "maximum": 600}},
             "required": ["action"]}},
    ],
    "constraints": {"readOnly": False, "permissionLevel": "write"},
}


class _Adapter:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name, args, ctx):
        self.calls.append((name, dict(args)))
        return ToolResult(ok=True, data={"tool": name, "args": args}, latency_ms=1)


def _build(timeout: float = 10.0):
    reg = ToolRegistry()
    adapter = _Adapter()
    reg.register(SPEC, adapter=adapter)
    audit = AuditLogger(AuditStore(max_memory=500, chain=True))
    bus = EventBus()
    tracer = Tracer(bus=bus)
    broker = ApprovalBroker(tools={"control_pump"}, timeout=timeout,
                            bus=bus, audit=audit)
    gw = MCPGateway(reg, audit, approvals=broker, tracer=tracer, bus=bus)
    app = create_app(reg, audit, gateway=gw, approvals=broker,
                     token_registry=TerminalTokenRegistry())
    return gw, broker, bus, adapter, TestClient(app)


def test_events_ws_stream_and_single_use_token():
    _gw, _broker, bus, _adapter, client = _build()
    token = client.post("/events/token").json()["token"]
    with client.websocket_connect(
            "/ws/events", subprotocols=[f"ua.events.{token}"]) as ws:
        bus.publish("system", message="hello")
        data = ws.receive_json()
        assert data["kind"] == "system"
        assert data["message"] == "hello"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
                "/ws/events", subprotocols=[f"ua.events.{token}"]):
            pass


def test_events_ws_rejects_missing_token():
    _gw, _broker, _bus, _adapter, client = _build()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/events"):
            pass


def test_events_http_poll_fallback():
    _gw, _broker, bus, _adapter, client = _build()
    bus.publish("system", message="poll")
    items = client.get("/events?since=0").json()["items"]
    assert any(e["kind"] == "system" and e["message"] == "poll" for e in items)


def test_hitl_approve_flow():
    gw, broker, _bus, adapter, client = _build()
    result: dict = {}

    def call():
        result.update(gw.call({
            "name": "control_pump",
            "arguments": {"action": "on", "duration": 300},
            "caller": "test", "permission_level": "write", "trace_id": "h1"}))

    t = threading.Thread(target=call)
    t.start()
    approval = _wait_pending(client)
    resp = client.post("/hitl/decide", json={
        "approval_id": approval["approval_id"],
        "decision": "approved", "decided_by": "pytest"})
    assert resp.status_code == 200
    t.join(timeout=5)
    assert result["isError"] is False
    assert adapter.calls[-1][1]["duration"] == 300
    audit_records = [r for r in gw.audit.store._ring if r["tool"] == "hitl.approval"]
    assert audit_records and audit_records[0]["guard_result"] == "passed"


def test_hitl_reject_flow():
    gw, _broker, _bus, adapter, client = _build()
    result: dict = {}

    def call():
        result.update(gw.call({
            "name": "control_pump",
            "arguments": {"action": "on", "duration": 300},
            "caller": "test", "permission_level": "write", "trace_id": "h2"}))

    t = threading.Thread(target=call)
    t.start()
    approval = _wait_pending(client)
    client.post("/hitl/decide", json={"approval_id": approval["approval_id"],
                                      "decision": "rejected"})
    t.join(timeout=5)
    assert result["isError"] is True
    assert result["meta"]["error_code"] == 1003
    assert adapter.calls == []


def test_hitl_modify_flow_uses_override_args():
    gw, _broker, _bus, adapter, client = _build()
    result: dict = {}

    def call():
        result.update(gw.call({
            "name": "control_pump",
            "arguments": {"action": "on", "duration": 300},
            "caller": "test", "permission_level": "write", "trace_id": "h3"}))

    t = threading.Thread(target=call)
    t.start()
    approval = _wait_pending(client)
    client.post("/hitl/decide", json={
        "approval_id": approval["approval_id"], "decision": "modify",
        "override_args": {"action": "on", "duration": 60}})
    t.join(timeout=5)
    assert result["isError"] is False
    assert adapter.calls[-1][1]["duration"] == 60


def test_read_only_call_skips_approval():
    gw, _broker, _bus, adapter, _client = _build()
    result = gw.call({"name": "get_state", "arguments": {},
                      "caller": "test", "permission_level": "read"})
    assert result["isError"] is False
    assert adapter.calls[-1][0] == "get_state"


def test_traces_endpoint_contains_genai_ready_spans():
    gw, _broker, _bus, _adapter, client = _build()
    gw.call({"name": "get_state", "arguments": {},
             "caller": "test", "permission_level": "read", "trace_id": "tr1"})
    items = client.get("/traces").json()["items"]
    trace = next(t for t in items if t["trace_id"] == "tr1")
    names = [s["name"] for s in trace["spans"]]
    assert "tool.get_state" in names
    assert trace["root"] == "tool.get_state"


def test_terminal_token_endpoint():
    _gw, _broker, _bus, _adapter, client = _build()
    body = client.post("/terminal/token").json()
    assert body["purpose"] == "terminal"
    assert body["ws_path"] == "/ws/terminal"
    assert len(body["token"]) > 20


def test_terminal_ws_echo_and_guard():
    """端到端：token 子协议 → 会话字节流 → 输入 Guard 拦截。"""
    _gw, _broker, _bus, _adapter, client = _build()
    token = client.post("/terminal/token").json()["token"]
    with client.websocket_connect(
            "/ws/terminal", subprotocols=[f"ua.terminal.{token}"]) as ws:
        first = ws.receive_json()
        assert first["kind"] == "terminal.state" and first["state"] == "running"
        assert ws.receive_json()["kind"] == "terminal.output"
        ws.send_json({"type": "input", "data": "echo ua_probe\r\n"})
        seen = ""
        for _ in range(40):
            msg = ws.receive_json()
            if msg.get("kind") == "terminal.output":
                seen += msg.get("data", "")
                if "ua_probe" in seen:
                    break
        assert "ua_probe" in seen

        ws.send_json({"type": "input", "data": "curl https://example.com\r\n"})
        blocked = ws.receive_json()
        assert blocked["kind"] == "terminal.state"
        assert blocked["state"] == "blocked"
        assert "网络" in blocked["reason"]


def _wait_pending(client: TestClient, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = client.get("/hitl/pending").json()["items"]
        if items:
            return items[0]
        time.sleep(0.05)
    raise AssertionError("审批请求未出现")
