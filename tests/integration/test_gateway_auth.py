"""P0 安全回归：Bearer Token 鉴权（BE-2）与服务端权限裁决（BE-1）。

约定：HUB_API_TOKEN 未设置 → 保持历史兼容（客户端 hint 生效，仅限本机）；
设置后 → /mcp 必须携带 Bearer，且权限由服务端裁决（认证=admin，未认证=read，
客户端上报的 permission_level 仅作为提示被忽略）。
"""

import os
import tempfile

from fastapi.testclient import TestClient

from core.contracts import CallContext, ToolResult
from core.gateway.server import MCPGateway, create_app
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry


class _StubAdapter:
    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        return ToolResult(ok=True, data={"done": True}, latency_ms=1)


_WRITE_SPEC = {
    "id": "iot.test_write",
    "type": "iot_device",
    "name": "写工具",
    "protocol": "mqtt",
    "endpoint": {"broker": "mqtt://127.0.0.1:1883",
                 "topic": "t/state", "command_topic": "t/command"},
    "capabilities": [{
        "name": "write_thing",
        "description": "写操作",
        "inputSchema": {"type": "object", "properties": {}},
        "readOnly": False,
    }],
    "constraints": {"readOnly": False, "permissionLevel": "write"},
}


def _registry_with_write_tool() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_WRITE_SPEC, adapter=_StubAdapter())
    return reg


def _call_params(**kw) -> dict:
    return {"name": "write_thing", "arguments": {},
            "caller": "test", "permission_level": "read", **kw}


# ---- 网关层（逻辑）----

def test_legacy_no_token_hint_admin_still_honored():
    """未启用鉴权：历史兼容，客户端 hint 仍生效（仅限本机回路模式）。"""
    gw = MCPGateway(_registry_with_write_tool(),
                    AuditLogger(AuditStore(max_memory=100)),
                    auth_enforced=False)
    res = gw.call(_call_params(permission_level="admin"))
    assert res["isError"] is False


def test_enforced_unauthenticated_hint_ignored():
    """启用鉴权后，未认证调用即使自报 admin 也被服务端压回 read → 1003。"""
    gw = MCPGateway(_registry_with_write_tool(),
                    AuditLogger(AuditStore(max_memory=100)),
                    auth_enforced=True)
    res = gw.call(_call_params(permission_level="admin"), authenticated=False)
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1003


def test_enforced_authenticated_gets_admin_regardless():
    """启用鉴权后，认证调用即使 hint 为 read 也由服务端定为 admin → 放行。"""
    gw = MCPGateway(_registry_with_write_tool(),
                    AuditLogger(AuditStore(max_memory=100)),
                    auth_enforced=True)
    res = gw.call(_call_params(permission_level="read"), authenticated=True)
    assert res["isError"] is False


# ---- HTTP 层（中间件）----

def _app_with_token(monkeypatch, token: str = "sekret-token"):
    monkeypatch.setenv("HUB_API_TOKEN", token)
    app = create_app(_registry_with_write_tool())
    monkeypatch.delenv("HUB_API_TOKEN")
    return app


def test_mcp_without_header_401(monkeypatch):
    app = _app_with_token(monkeypatch)
    client = TestClient(app)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                                  "method": "tools/list", "params": {}})
    assert r.status_code == 401


def test_mcp_wrong_token_401(monkeypatch):
    app = _app_with_token(monkeypatch)
    client = TestClient(app)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                                  "method": "tools/list", "params": {}},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_mcp_with_token_calls_write_tool(monkeypatch):
    app = _app_with_token(monkeypatch)
    client = TestClient(app)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2,
                                  "method": "tools/call",
                                  "params": _call_params(permission_level="read")},
                    headers={"Authorization": "Bearer sekret-token"})
    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert body["result"]["isError"] is False


def test_healthz_unprotected(monkeypatch):
    app = _app_with_token(monkeypatch)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_workflows_recent_protected(monkeypatch):
    app = _app_with_token(monkeypatch)
    client = TestClient(app)
    assert client.get("/workflows/recent").status_code == 401
    ok = client.get("/workflows/recent",
                    headers={"Authorization": "Bearer sekret-token"})
    assert ok.status_code == 200


def test_no_token_env_middleware_disabled(monkeypatch):
    monkeypatch.delenv("HUB_API_TOKEN", raising=False)
    app = create_app(_registry_with_write_tool())
    client = TestClient(app)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                                  "method": "tools/list", "params": {}})
    assert r.status_code == 200