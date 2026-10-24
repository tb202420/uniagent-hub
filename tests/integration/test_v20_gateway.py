"""v2.0 网关端点测试：/metrics（Prometheus）/ /scenes（场景模板）/ /workflows/events。"""

from fastapi.testclient import TestClient

from core.contracts import CallContext, ToolResult
from core.gateway.server import MCPGateway, create_app
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.workflow.engine import WorkflowEngine


class _Stub:
    def call_tool(self, name, args, ctx: CallContext) -> ToolResult:
        return ToolResult(ok=True, data={"v": 1}, latency_ms=3)


def _app_with_call():
    spec = {
        "id": "iot.m", "type": "iot_device", "name": "m", "protocol": "mqtt",
        "endpoint": {"broker": "mqtt://127.0.0.1:1883", "topic": "t/state"},
        "capabilities": [{"name": "get_x", "description": "读",
                          "readOnly": True,
                          "inputSchema": {"type": "object", "properties": {}}}],
        "constraints": {"readOnly": True, "permissionLevel": "read"},
    }
    reg = ToolRegistry()
    reg.register(spec, adapter=_Stub())
    gw = MCPGateway(reg, AuditLogger(AuditStore(max_memory=20)))
    gw.workflow = WorkflowEngine(gw)
    gw.workflow.register_workflows({"demo": {"steps": [
        {"id": "s1", "tool": "get_x", "args": {}}]}})
    return create_app(reg, gateway=gw), gw


def test_metrics_endpoint_counts_calls():
    app, _ = _app_with_call()
    client = TestClient(app)
    client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "get_x", "arguments": {}}})
    body = client.get("/metrics").text
    assert "uniagent_tool_calls_total" in body
    assert 'tool="get_x"' in body and 'result="ok"' in body


def test_scenes_endpoint_lists_templates():
    app, _ = _app_with_call()
    items = TestClient(app).get("/scenes").json()["items"]
    ids = {s["id"] for s in items}
    assert len(items) >= 5
    assert {"greenhouse-irrigate", "env-snapshot"} <= ids
    write_scenes = [s for s in items if s.get("write")]
    assert write_scenes, "至少一个写场景（简易模式确认卡片依赖）"


def test_workflow_events_endpoint():
    app, gw = _app_with_call()
    gw.workflow.run("demo")
    items = TestClient(app).get("/workflows/events").json()["items"]
    kinds = [e["kind"] for e in items]
    assert "workflow" in kinds and "step" in kinds
    # 增量：since=最大 seq 后应为空
    max_seq = max(e["seq"] for e in items)
    assert TestClient(app).get(f"/workflows/events?since={max_seq}").json()["items"] == []
