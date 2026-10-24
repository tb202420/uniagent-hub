"""v2.0 引擎与鉴权新能力测试：并行分支 / 三元表达式 / DAG 深度上限 / 事件流 / JWT。"""

import threading
import time

import pytest

_SEC = "s3cret-0123456789abcdef0123456789abcdef"

from core.guard.tokens import TokenError, issue_token, verify_token
from core.gateway.server import MCPGateway, create_app
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.workflow.engine import WorkflowEngine, MAX_DAG_DEPTH
from core.workflow.expr import safe_eval, ExprError


# ---- 三元表达式 ----

def test_ternary_true_false_branch():
    assert safe_eval("1 < 2 ? 'on' : 'off'") == "on"
    assert safe_eval("1 > 2 ? 'on' : 'off'") == "off"


def test_ternary_nested_and_in_parens():
    assert safe_eval("1 ? 2 ? 'a' : 'b' : 'c'") == "a"      # 右结合
    assert safe_eval("(1 > 0 ? 5 : 6) + 1") == 6             # 括号内可用


def test_ternary_missing_colon_raises():
    with pytest.raises(ExprError):
        safe_eval("1 ? 'a'")


# ---- 工作流：并行 / 深度 / 事件 ----

class _SlowGateway:
    """每个工具固定耗时 delay 秒，用于验证并行收益与依赖正确性。"""

    def __init__(self, delay: float = 0.3) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def call(self, params, **_kw):
        with self.lock:
            self.calls.append(params["name"])
        time.sleep(self.delay)
        import json as _json
        return {"content": [{"type": "text", "text": _json.dumps(
            {"done": params["name"]})}],
            "isError": False, "meta": {"latency_ms": int(self.delay * 1000)}}


def _engine_with(gateway, wfs: dict) -> WorkflowEngine:
    e = WorkflowEngine(gateway)
    e.register_workflows(wfs)
    return e


def test_parallel_layers_run_concurrently():
    gw = _SlowGateway(0.3)
    e = _engine_with(gw, {"fan": {"parallel": True, "steps": [
        {"id": f"s{i}", "tool": f"t{i}", "args": {}} for i in range(4)]}})
    t0 = time.time()
    s = e.run("fan")
    elapsed = time.time() - t0
    assert s["ok"] and s["parallel"] is True
    # 串行需 ~1.2s；并行单层应明显更快（CI 慢机器余量放宽到 0.95s）
    assert elapsed < 0.95, f"并行未生效: {elapsed:.2f}s"


def test_parallel_respects_dependencies():
    gw = _SlowGateway(0.05)
    e = _engine_with(gw, {"chain": {"parallel": True, "steps": [
        {"id": "a", "tool": "t_a", "args": {}},
        {"id": "b", "tool": "t_b", "args": {}, "depends_on": ["a"]}]}})
    s = e.run("chain")
    assert [st["status"] for st in s["steps"]] == ["ok", "ok"]
    assert gw.calls.index("t_a") < gw.calls.index("t_b")     # 依赖顺序保持


def test_dag_depth_cap_rejected():
    steps = [{"id": "s0", "tool": "t", "args": {}}]
    for i in range(1, MAX_DAG_DEPTH + 2):
        steps.append({"id": f"s{i}", "tool": "t", "args": {},
                      "depends_on": [f"s{i-1}"]})
    with pytest.raises(Exception, match="深度"):
        _engine_with(_SlowGateway(), {"too_deep": {"steps": steps}})


def test_events_stream_incremental():
    gw = _SlowGateway(0.01)
    e = _engine_with(gw, {"wf": {"steps": [
        {"id": "s1", "tool": "t1", "args": {}},
        {"id": "s2", "tool": "t2", "args": {}, "depends_on": ["s1"]}]}})
    s = e.run("wf")
    events = e.events(since=0)
    kinds = [ev["kind"] for ev in events]
    assert kinds.count("workflow") == 2          # running + finish
    assert kinds.count("step") == 2
    assert all(ev["wf"] == s["trace_id"] for ev in events)
    mid = events[1]["seq"]                        # 增量轮询：只取之后
    assert all(ev["seq"] > mid for ev in e.events(since=mid))


# ---- JWT 短期令牌 ----

def test_jwt_issue_verify_roundtrip():
    tok = issue_token("alice", "write", ttl=60, tools=["control_pump"],
                      secret=_SEC)
    claims = verify_token(tok, secret=_SEC)
    assert claims == {"caller": "alice", "perm": "write",
                      "tools": ["control_pump"]}


def test_jwt_expired_and_bad_signature():
    tok = issue_token("bob", "read", ttl=-5, secret=_SEC)
    with pytest.raises(TokenError, match="过期"):
        verify_token(tok, secret=_SEC)
    tok = issue_token("bob", "read", ttl=60, secret=_SEC)
    with pytest.raises(TokenError):
        verify_token(tok, secret="wrong-key-0123456789abcdef0123456789")


def _registry_with_write_tool():
    from core.contracts import CallContext, ToolResult

    class _Stub:
        def call_tool(self, name, args, ctx: CallContext) -> ToolResult:
            return ToolResult(ok=True, data={"done": True}, latency_ms=1)

    spec = {
        "id": "iot.w", "type": "iot_device", "name": "w", "protocol": "mqtt",
        "endpoint": {"broker": "mqtt://127.0.0.1:1883", "topic": "t/state",
                     "command_topic": "t/cmd"},
        "capabilities": [{"name": "write_thing",
                          "description": "写", "readOnly": False,
                          "inputSchema": {"type": "object", "properties": {}}}],
        "constraints": {"readOnly": False, "permissionLevel": "write"},
    }
    reg = ToolRegistry()
    reg.register(spec, adapter=_Stub())
    return reg


def test_gateway_jwt_identity_and_tool_scope():
    """JWT 身份裁决：perm 来自 claims；tools 白名单外的调用 1003。"""
    import os
    old = os.environ.get("HUB_AUTH_MODE"), os.environ.get("HUB_JWT_SECRET")
    os.environ["HUB_AUTH_MODE"] = "jwt"
    os.environ["HUB_JWT_SECRET"] = "s3cret"
    try:
        gw = MCPGateway(_registry_with_write_tool(),
                        AuditLogger(AuditStore(max_memory=20)))
        assert gw.auth_enforced is True
        # read 令牌调写工具 → 1003
        r = gw.call({"name": "write_thing", "arguments": {}},
                    auth_identity={"caller": "u1", "perm": "read", "tools": []})
        assert r["isError"] and r["meta"]["error_code"] == 1003
        # write 令牌 + tools 白名单不含目标 → 1003
        r = gw.call({"name": "write_thing", "arguments": {}},
                    auth_identity={"caller": "u1", "perm": "write",
                                   "tools": ["other"]})
        assert r["isError"] and r["meta"]["error_code"] == 1003
        # write 令牌 + 白名单含目标 → 放行
        r = gw.call({"name": "write_thing", "arguments": {}},
                    auth_identity={"caller": "u1", "perm": "write",
                                   "tools": ["write_thing"]})
        assert r["isError"] is False
    finally:
        for k, v in zip(("HUB_AUTH_MODE", "HUB_JWT_SECRET"), old):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_http_jwt_middleware_401_and_pass(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HUB_AUTH_MODE", "jwt")
    monkeypatch.setenv("HUB_JWT_SECRET", _SEC)
    app = create_app(_registry_with_write_tool())
    client = TestClient(app)
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                                     "method": "tools/list",
                                     "params": {}}).status_code == 401
    tok = issue_token("alice", "admin", ttl=60, secret=_SEC)
    ok = client.post("/mcp", headers={"Authorization": f"Bearer {tok}"},
                     json={"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                           "params": {}})
    assert ok.status_code == 200
