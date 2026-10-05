"""FastMCP 4 兼容前端（改进方案 §2 + §3 合并落地）。

协议层委托给 FastMCP 4（streamable HTTP；现代 2026-07-28 无状态规范与旧版
握手协议由其原生按连接协商），工具以 **4 个元工具**（渐进式发现）暴露；
**执行仍经自研网关的 Guard 管道与审计**（execute_tool 透传 tools/call 全链路，
安全语义 1001/1002/1003/1004/1007 完全一致）。

自研网关（core/gateway/server.py）保留为**默认主路径与回退路径**：
    python main.py --gateway fastmcp     # 启用本前端（默认 selfdev）

调用方身份与权限：HUB_FASTMCP_CALLER（默认 fastmcp_client）/
HUB_FASTMCP_PERMISSION（默认 read；需要写操作时设 write）。
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from typing import Any

from core.gateway.meta_tools import MetaTools


class BearerTokenMiddleware:
    """纯 ASGI Bearer 鉴权（P2：覆盖 FastMCP 前端，与自研网关同一语义）。

    ``--gateway fastmcp`` 走 FastMCP 自己的 ASGI 应用，不经过 create_app 的
    Bearer 中间件（P0-BE-2 只护自研路径）；设置 HUB_API_TOKEN 后由本中间件
    在协议前端入口做同样校验：401 + JSON-RPC -32001，恒时比较。
    ``/mcp``（含 ``/mcp/``）受保护，其余路径（如健康检查）放行。
    """

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        if secrets.compare_digest(headers.get("authorization", ""), self._expected):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32001,
                                     "message": "未授权：缺少或错误的 Bearer Token"}},
                          ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": body})


def bearer_middleware() -> list[Any] | None:
    """HUB_API_TOKEN 已设置时返回 Starlette 中间件列表，否则 None（本地回路兼容）。"""
    token = os.environ.get("HUB_API_TOKEN", "").strip()
    if not token:
        return None
    from starlette.middleware import Middleware
    return [Middleware(BearerTokenMiddleware, token=token)]


def build_fastmcp_server(gateway: Any, *, caller: str | None = None,
                         permission_level: str | None = None) -> Any:
    """构建 FastMCP 服务器：4 元工具 → 自研网关（Guard + 审计 + 编排）。"""
    from fastmcp import FastMCP
    from fastmcp.exceptions import ToolError

    caller = caller or os.environ.get("HUB_FASTMCP_CALLER", "fastmcp_client")
    level = permission_level or os.environ.get("HUB_FASTMCP_PERMISSION", "read")

    # 前端使用元工具目录；确保网关侧同时启用（execute_tool 需要 meta 分支）
    meta = gateway.meta_tools or MetaTools(gateway)
    gateway.meta_tools = meta
    defs = {d["name"]: d for d in meta.definitions()}

    mcp = FastMCP("uniagent-hub")

    def _call(name: str, arguments: dict[str, Any]) -> str:
        """经自研网关调用（Guard 管道 + 审计），错误转换为 FastMCP ToolError。

        internal=True：FastMCP 前端是受信的进程内前端——传输层已由 Bearer
        中间件校验（未启用鉴权时仅本机回路），身份沿用 HUB_FASTMCP_CALLER /
        HUB_FASTMCP_PERMISSION；未启用鉴权时与历史行为逐字段一致。
        """
        res = gateway.call({
            "name": name,
            "arguments": arguments,
            "caller": caller,
            "trace_id": uuid.uuid4().hex[:8],
            "permission_level": level,
        }, internal=True)
        text = (res.get("content") or [{}])[0].get("text", "")
        if res.get("isError"):
            raise ToolError(text)
        return text

    @mcp.tool(name="discover_tools",
              description=defs["discover_tools"]["description"])
    def discover_tools(domain: str = "", query: str = "") -> str:
        args: dict[str, Any] = {}
        if domain:
            args["domain"] = domain
        if query:
            args["query"] = query
        return _call("discover_tools", args)

    @mcp.tool(name="get_tool_schema",
              description=defs["get_tool_schema"]["description"])
    def get_tool_schema(name: str) -> str:
        return _call("get_tool_schema", {"name": name})

    @mcp.tool(name="execute_tool",
              description=defs["execute_tool"]["description"])
    def execute_tool(tool: str, arguments: dict | None = None) -> str:
        return _call("execute_tool",
                     {"tool": tool, "arguments": arguments or {}})

    @mcp.tool(name="refresh_registry",
              description=defs["refresh_registry"]["description"])
    def refresh_registry() -> str:
        return _call("refresh_registry", {})

    return mcp