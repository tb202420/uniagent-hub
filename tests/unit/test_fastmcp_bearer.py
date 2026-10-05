"""P2 安全回归：FastMCP 前端的 Bearer 覆盖与受信中继。

--gateway fastmcp 此前绕过 create_app 的 Bearer 中间件（P0-BE-2 只护自研
路径）；修复后：① HUB_API_TOKEN 设置时 FastMCP ASGI 入口同样校验
（401 + -32001，恒时比较）；② 前端经 internal=True 中继，身份取自
HUB_FASTMCP_CALLER/PERMISSION，鉴权模式下写操作按配置裁决、不降权也不旁路。
"""

import asyncio
import json

import pytest

pytest.importorskip("fastmcp")

from core.contracts import CallContext, ToolResult
from core.gateway.fastmcp_server import (
    BearerTokenMiddleware, bearer_middleware, build_fastmcp_server,
)
from core.gateway.meta_tools import MetaTools
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry

_TOKEN = "sekret-fastmcp-token"


def _dummy_app(marker: list):
    async def app(scope, receive, send):
        marker.append(scope["path"])
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})
    return app


async def _call_asgi(app, path: str, authorization: str | None = None):
    """裸 ASGI 调用（不触发 lifespan），返回 (status, body bytes)。"""
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("ascii")))
    scope = {"type": "http", "method": "POST", "path": path,
             "headers": headers, "query_string": b""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"")
                    for m in sent if m["type"] == "http.response.body")
    return start["status"], body


def _middleware(marker: list) -> BearerTokenMiddleware:
    return BearerTokenMiddleware(_dummy_app(marker), _TOKEN)


def test_mcp_without_header_401():
    marker: list = []
    status, body = asyncio.run(_call_asgi(_middleware(marker), "/mcp"))
    assert status == 401
    assert json.loads(body)["error"]["code"] == -32001
    assert marker == []                            # 未到达内层应用


def test_mcp_wrong_token_401():
    marker: list = []
    status, _ = asyncio.run(_call_asgi(_middleware(marker), "/mcp",
                                       "Bearer wrong"))
    assert status == 401
    assert marker == []


def test_mcp_with_token_passes_through():
    marker: list = []
    status, body = asyncio.run(_call_asgi(_middleware(marker), "/mcp",
                                          f"Bearer {_TOKEN}"))
    assert status == 200
    assert body == b"ok"
    assert marker == ["/mcp"]


def test_non_mcp_path_unprotected():
    marker: list = []
    status, _ = asyncio.run(_call_asgi(_middleware(marker), "/healthz"))
    assert status == 200
    assert marker == ["/healthz"]


def test_mcp_path_with_trailing_slash_protected():
    marker: list = []
    status, _ = asyncio.run(_call_asgi(_middleware(marker), "/mcp/"))
    assert status == 401
    assert marker == []


def test_bearer_middleware_env_toggle(monkeypatch):
    monkeypatch.delenv("HUB_API_TOKEN", raising=False)
    assert bearer_middleware() is None             # 本地回路兼容模式
    monkeypatch.setenv("HUB_API_TOKEN", _TOKEN)
    mw = bearer_middleware()
    assert mw is not None and mw[0].cls is BearerTokenMiddleware
    assert mw[0].kwargs["token"] == _TOKEN


# ---- 受信中继：鉴权模式下 FastMCP 前端写操作按 HUB_FASTMCP_PERMISSION 裁决 ----

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


class _StubAdapter:
    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        return ToolResult(ok=True, data={"done": True}, latency_ms=1)


def _enforced_gateway() -> MCPGateway:
    reg = ToolRegistry()
    reg.register(_WRITE_SPEC, adapter=_StubAdapter())
    return MCPGateway(reg, AuditLogger(AuditStore(max_memory=100)),
                      auth_enforced=True)


def test_enforced_write_allowed_with_write_permission(monkeypatch):
    """HUB_FASTMCP_PERMISSION=write：internal 中继按配置裁决 → 放行。"""
    monkeypatch.setenv("HUB_FASTMCP_PERMISSION", "write")
    gw = _enforced_gateway()
    server = build_fastmcp_server(gw)

    async def run():
        from fastmcp import Client
        async with Client(server) as client:
            return await client.call_tool(
                "execute_tool", {"tool": "write_thing", "arguments": {}})

    res = asyncio.run(run())
    assert '"done"' in str(res)
    assert gw.meta_tools is not None


def test_enforced_write_denied_with_default_read(monkeypatch):
    """默认 read：internal 中继不旁路权限 → 1003（ToolError）。"""
    monkeypatch.delenv("HUB_FASTMCP_PERMISSION", raising=False)
    gw = _enforced_gateway()
    server = build_fastmcp_server(gw)

    async def run():
        from fastmcp import Client
        async with Client(server) as client:
            return await client.call_tool(
                "execute_tool", {"tool": "write_thing", "arguments": {}})

    with pytest.raises(Exception) as exc:
        asyncio.run(run())
    assert "1003" in str(exc.value)


def test_meta_execute_relay_keeps_guard_but_not_downgrade():
    """execute_tool 中继（MetaTools.execute → internal=True）：
    鉴权模式下权限随已裁决的 ctx 传递，不被压回匿名 read。"""
    gw = _enforced_gateway()
    gw.meta_tools = MetaTools(gw)
    res = gw.call({"name": "execute_tool",
                   "arguments": {"tool": "write_thing", "arguments": {}},
                   "caller": "authenticated",          # 服务端裁决后的身份（外层 ctx）
                   "permission_level": "admin"},
                  internal=True)
    assert res["isError"] is False
    assert '"done"' in res["content"][0]["text"]
