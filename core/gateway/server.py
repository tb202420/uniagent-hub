"""MCP 路由网关：FastAPI + JSON-RPC 2.0，实现 docs/api.md §2 契约。

端点：
  POST /mcp      — MCP 方法（initialize / ping / server/discover / tools/list / tools/call）
  GET  /healthz  — 健康检查

路由：tools/call 按工具名 → Registry 解析 (spec, capability) → owner 适配器。
Guard 管道（横切）：存在性 → 权限 → 限流 → 参数校验 → 适配器执行 → 审计。
run_workflow 由 WorkflowEngine 提供（每步仍走本 Guard 管道，不旁路安全）。
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.adapters.plugins import adapter_health
from core.contracts import (
    CallContext, ToolResult,
    E_TOOL_NOT_FOUND, E_PERMISSION_DENIED, E_RATE_LIMITED,
    E_INVALID_ARGS, E_INJECTION_BLOCKED, E_INTERNAL,
)
from core.guard.attestation import attestation_report, schema_hash
from core.guard.audit import AuditLogger, AuditStore, default_logger
from core.guard.ratelimit import RateLimiter
from core.guard.validation import validate_args
from core.registry.registry import ToolRegistry

# 无状态规范版本号（docs/api.md §2.3）
SUPPORTED_PROTOCOL_VERSIONS = ["2026-07-28", "2025-11-25"]
# 工作流整体限流（Guard v2：防 Agent 无限触发编排）
WORKFLOW_RATE_LIMIT = "10/m"


class MCPGateway:
    """MCP 网关核心逻辑（与 Web 框架解耦，便于单测）。"""

    def __init__(self, registry: ToolRegistry, audit: AuditLogger | None = None,
                 workflow_engine: Any | None = None,
                 rate_limiter: RateLimiter | None = None,
                 meta_tools: Any | None = None,
                 auth_enforced: bool | None = None) -> None:
        self.registry = registry
        self.audit = audit or default_logger
        self.workflow = workflow_engine
        self.rate_limiter = rate_limiter or RateLimiter()
        # 渐进式工具发现（改进方案 §3）：启用后 tools/list 仅返回 4 个元工具
        self.meta_tools = meta_tools
        # Bearer Token 鉴权（P0-BE-2）：设置 HUB_API_TOKEN 后 /mcp 需带
        # Authorization: Bearer <token>；未设置时保持本地回路兼容模式。
        self.auth_enforced = (
            bool(os.environ.get("HUB_API_TOKEN"))
            if auth_enforced is None else auth_enforced)

    # ---- server/discover / tools/list ----

    def discover(self) -> dict[str, Any]:
        caps: dict[str, Any] = {"tools": {"listChanged": True}}
        if self.workflow is not None:
            caps["workflows"] = {"supported": True}
        return {
            "protocolVersion": "2026-07-28",
            "supportedVersions": SUPPORTED_PROTOCOL_VERSIONS,
            "capabilities": caps,
            "serverInfo": {"name": "uniagent-hub", "version": "0.3.0"},
        }

    def list_tools(self) -> dict[str, Any]:
        # 注册中心是唯一事实来源：run_workflow 已由 build 流程注册进 registry
        # （registry.register_tool），tools/list 与 /healthz 计数天然一致（A1 修复）。
        if self.meta_tools is not None:
            # 渐进式发现模式（HUB_META_TOOLS=1）：只暴露 4 个元工具，
            # Agent 按需用 get_tool_schema 拉取具体工具签名（改进方案 §3）
            return {"tools": self.meta_tools.definitions()}
        return {"tools": self.registry.list_tools()}

    # ---- tools/call ----

    def call(self, params: dict[str, Any], *,
             authenticated: bool = False,
             internal: bool = False) -> dict[str, Any]:
        tool_name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        # trace_id：客户端可作提示，但审计主键冲突风险独立处理（P2-BE-5）
        trace_id = params.get("trace_id") or uuid.uuid4().hex[:8]
        # P0-BE-1 权限服务端裁决 + P1-BE-3 限流 key 服务端派生：
        #   启用鉴权时，客户端上报的 permission_level / caller / rate_scope
        #   一律不作为安全依据（仅进程内工作流引擎的 internal 调用被信任）。
        client_level = params.get("permission_level", "read")
        if self.auth_enforced:
            if internal:
                # 工作流引擎进程内调用：权限随工作流入参（受信任路径）
                caller = params.get("caller", "workflow")
                permission_level = params.get("permission_level", "read")
                rate_scope = params.get("rate_scope", "external")
            elif authenticated:
                caller = "authenticated"
                permission_level = "admin"
                rate_scope = "external"
            else:
                caller = "anonymous"
                permission_level = "read"
                rate_scope = "external"
        else:
            # 本地回路兼容模式（默认绑定 127.0.0.1）
            caller = params.get("caller", "demo_agent")
            permission_level = client_level
            rate_scope = params.get("rate_scope", "external")
        ctx = CallContext(trace_id=trace_id, caller=caller,
                          permission_level=permission_level)

        if self.meta_tools is not None and self.meta_tools.handles(tool_name):
            return self._call_meta(ctx, tool_name, args)

        if tool_name == "run_workflow":
            return self._call_workflow(ctx, args)

        resolved = self.registry.resolve(tool_name)
        if resolved is None:
            return self._finish(ctx, tool_name, args, ToolResult(
                ok=False, error_code=E_TOOL_NOT_FOUND, error_msg=f"工具不存在: {tool_name}"))

        spec, cap = resolved

        # Guard：权限校验（能力级粒度，ERR-03 修复）
        # 优先级：cap.permissionLevel > (readOnly ? "read" : spec.constraints.permissionLevel)
        # readOnly 能力自动降为 read（最小权限）；写能力沿用资源级声明；
        # cap.permissionLevel 可显式覆盖（设备级加固场景，如门锁状态查询要求 write）
        required = cap.permissionLevel or (
            "read" if cap.readOnly else spec.constraints.permissionLevel)
        if _level_rank(ctx.permission_level) < _level_rank(required):
            return self._finish(ctx, tool_name, args, ToolResult(
                ok=False, error_code=E_PERMISSION_DENIED,
                error_msg=f"权限不足: 需要 {required}，当前 {ctx.permission_level}"))

        # Guard：限流（按 tool+caller+scope 滑动窗口；scope 隔离外部/工作流内调用）
        rl = spec.constraints.rateLimit or cap.rateLimit
        if rl and not self.rate_limiter.check(tool_name, caller, rl, rate_scope):
            return self._finish(ctx, tool_name, args, ToolResult(
                ok=False, error_code=E_RATE_LIMITED,
                error_msg=f"超出速率限制 {rl}（tool={tool_name}, caller={caller}, scope={rate_scope}）"))

        # Guard：参数校验（横切，所有类型工具统一执行）
        norm_args = {k: (v.replace("\\", "/") if isinstance(v, str) else v)
                     for k, v in args.items()}
        errors = validate_args(cap.inputSchema, norm_args, cap.paramPatterns)
        if errors:
            code = (E_INJECTION_BLOCKED if any("注入防护" in e or "非法字符" in e for e in errors)
                    else E_INVALID_ARGS)
            return self._finish(ctx, tool_name, args, ToolResult(
                ok=False, error_code=code, error_msg="; ".join(errors)))

        owner = self.registry.owner_of(spec.id)
        if owner is None:
            return self._finish(ctx, tool_name, args, ToolResult(
                ok=False, error_code=E_INTERNAL, error_msg=f"资源 {spec.id} 无负责适配器"))

        # 适配器执行（适配器内部再做参数校验 / 注入防护 / 超时，纵深防御）
        result = owner.call_tool(tool_name, norm_args, ctx)
        return self._finish(ctx, tool_name, args, result)

    # ---- 工作流调用（run_workflow）----

    def _call_workflow(self, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
        if self.workflow is None:
            return self._finish(ctx, "run_workflow", args, ToolResult(
                ok=False, error_code=E_TOOL_NOT_FOUND, error_msg="run_workflow 未启用"))

        # 限流：工作流整体（防无限触发编排）
        if not self.rate_limiter.check("run_workflow", ctx.caller, WORKFLOW_RATE_LIMIT):
            return self._finish(ctx, "run_workflow", args, ToolResult(
                ok=False, error_code=E_RATE_LIMITED,
                error_msg=f"工作流触发超限 {WORKFLOW_RATE_LIMIT}"))

        # 权限：run_workflow 为 write 级（可触发写操作）
        if _level_rank(ctx.permission_level) < _level_rank("write"):
            return self._finish(ctx, "run_workflow", args, ToolResult(
                ok=False, error_code=E_PERMISSION_DENIED,
                error_msg="运行工作流需要 write 权限"))

        # 参数校验（复用 Guard：workflow enum + required）
        schema = self.workflow.tool_definition()["inputSchema"]
        errors = validate_args(schema, args)
        if errors:
            return self._finish(ctx, "run_workflow", args, ToolResult(
                ok=False, error_code=E_INVALID_ARGS, error_msg="; ".join(errors)))

        try:
            summary = self.workflow.run(
                args["workflow"], params=args.get("params", {}),
                caller=ctx.caller, trace_id=ctx.trace_id,
                permission_level=ctx.permission_level,
            )
        except Exception as e:  # 蓝图校验失败等
            return self._finish(ctx, "run_workflow", args, ToolResult(
                ok=False, error_code=E_INVALID_ARGS, error_msg=f"工作流执行失败: {e}"))

        latency = sum(s.get("latency_ms", 0) for s in summary["steps"])
        if not summary["ok"]:
            failed = [f"{s['id']}({s['tool']}):{s.get('error','')[:60]}"
                      for s in summary["steps"] if s["status"] == "error"]
            return self._finish(ctx, "run_workflow", args, ToolResult(
                ok=False, error_code=E_INTERNAL,
                error_msg="工作流部分步骤失败: " + "; ".join(failed),
                data=json.dumps(summary, ensure_ascii=False),
                latency_ms=latency))
        return self._finish(ctx, "run_workflow", args, ToolResult(
            ok=True,
            data=json.dumps(summary, ensure_ascii=False),
            latency_ms=latency))

    # ---- 元工具调用（渐进式发现，改进方案 §3）----

    def _call_meta(self, ctx: CallContext, tool_name: str,
                   args: dict[str, Any]) -> dict[str, Any]:
        """元工具分发。

        execute_tool：透传被调工具的完整 Guard 管道（1001/1002/1003/1004/1007
        等语义与 tools/call 完全一致，安全不旁路）；
        其余三个（discover/get_tool_schema/refresh）为只读查询，走常规审计。
        """
        if tool_name == "execute_tool":
            target = str(args.get("tool") or "").strip()
            if self.meta_tools.handles(target):
                # 递归防护：禁止通过 execute_tool 嵌套调用元工具
                return self._finish(ctx, "execute_tool", args, ToolResult(
                    ok=False, error_code=E_INVALID_ARGS,
                    error_msg="不允许通过 execute_tool 嵌套调用元工具"))
            inner = self.meta_tools.execute(
                target, args.get("arguments") or {}, ctx)
            inner_meta = inner.get("meta") or {}
            ok = not inner.get("isError")
            # 元层调用也落审计（被调工具自身由内部调用链另行审计，链路完整可追溯）
            self.audit.record(
                trace_id=ctx.trace_id, caller=ctx.caller, tool="execute_tool",
                args={"tool": target}, guard_result="passed" if ok else "blocked",
                block_reason="" if ok else (inner.get("content") or [{}])[0].get("text", "")[:200],
                result={"ok": ok}, latency_ms=inner_meta.get("latency_ms", 0),
                error_code=inner_meta.get("error_code", 0) or 0,
                schema_hash=self._schema_hash("execute_tool"))
            return inner

        schema = self.meta_tools.schema_of(tool_name)
        errors = validate_args(schema, args)
        if errors:
            return self._finish(ctx, tool_name, args, ToolResult(
                ok=False, error_code=E_INVALID_ARGS, error_msg="; ".join(errors)))
        return self._finish(ctx, tool_name, args,
                            self.meta_tools.dispatch(tool_name, args))

    # ---- 工具清单证明（改进方案 §5.1）----

    def attestation(self) -> dict[str, Any]:
        """证明报告：全部工具的内容哈希 + 可选 Ed25519 签名。

        设置 HUB_ATTESTATION_KEY（PEM 密钥路径）后附签名；
        未设置时只返回内容哈希（signed=false）。
        """
        key_path = os.environ.get("HUB_ATTESTATION_KEY", "").strip()
        return attestation_report(self.registry.list_tools(),
                                  key_path if key_path else None)

    def _schema_hash(self, tool_name: str) -> str:
        """被调工具定义的内容哈希（工具投毒防护：审计可追溯其确切版本）。

        注册中心查不到时回退到**元工具定义**（execute_tool 等，A2 修复）——
        保证每条审计记录（含元层记录）的 schema_hash 均为"被调工具定义的哈希"，
        语义统一、非空（未知工具除外）。
        """
        try:
            for t in self.registry.list_tools():
                if t.get("name") == tool_name:
                    return schema_hash(t)
            if self.meta_tools is not None:
                for t in self.meta_tools.definitions():
                    if t.get("name") == tool_name:
                        return schema_hash(t)
        except Exception:  # noqa: BLE001 - 哈希失败不影响调用主链路
            pass
        return ""

    # ---- 审计封装 ----

    def _finish(self, ctx: CallContext, tool_name: str, args: dict,
                result: ToolResult) -> dict[str, Any]:
        guard_result = "blocked" if not result.ok else "passed"
        self.audit.record(
            trace_id=ctx.trace_id, caller=ctx.caller, tool=tool_name, args=args,
            guard_result=guard_result, block_reason=result.error_msg,
            result={"ok": result.ok}, latency_ms=result.latency_ms,
            # A2 修复：数字错误码落审计（Dashboard 可按 1007/1003/1004 检索）
            error_code=result.error_code or 0,
            # 改进方案 §5.1：审计携带工具 Schema 内容哈希（工具投毒防护追溯）
            schema_hash=self._schema_hash(tool_name),
        )
        if not result.ok:
            text = f"[error {result.error_code}] {result.error_msg}"
            if result.data is not None:  # 携带结构化明细（如工作流部分失败）
                text += "\n" + _to_text(result.data)
            return {
                "content": [{"type": "text", "text": text}],
                "isError": True,
                "meta": {"error_code": result.error_code, "guard": "guard_pipeline"},
            }
        return {
            "content": [{"type": "text", "text": _to_text(result.data)}],
            "isError": False,
            "meta": {"latency_ms": result.latency_ms},
        }


def _to_text(data: Any) -> str:
    """工具输出统一为 JSON 文本（dict/list 用 json.dumps）。

    适配器可能返回 dict（如 MQTT 的 get_ac_state 完整状态对象）；
    直接 str() 会得到 Python repr（单引号），CLI 调用方无法用 jq/JSON 解析，
    因此统一序列化为 JSON —— 对 Agent 与 CLI 两类消费方都是稳定契约。
    """
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False)
    return str(data)


def _level_rank(level: str) -> int:
    return {"read": 0, "write": 1, "admin": 2}.get(level, 0)


# ---- FastAPI 应用 ----

def create_app(registry: ToolRegistry, audit: AuditLogger | None = None,
               workflow_engine: Any | None = None,
               rate_limiter: RateLimiter | None = None,
               gateway: "MCPGateway | None" = None,
               adapters: list[tuple[str, Any]] | None = None) -> FastAPI:
    """构建 FastAPI 应用。可传预构建 gateway（用于工作流引擎与网关互引）。

    adapters：[(名称, 适配器实例)]，提供时 /healthz 汇总各适配器健康状态
    （生命周期回调 on_health_check，改进方案 §4）。
    """
    gateway = gateway or MCPGateway(registry, audit, workflow_engine, rate_limiter)
    app = FastAPI(title="UniAgent Hub Gateway", version="0.3.0")

    # P0-BE-2：Bearer Token 鉴权（方案 C）。设置 HUB_API_TOKEN 后，/mcp 与
    # /workflows/recent 必须携带 Authorization: Bearer <token>；
    # 未设置时保持本地回路兼容模式（配合 main.py 默认绑定 127.0.0.1）。
    api_token = os.environ.get("HUB_API_TOKEN", "")

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        if api_token and request.url.path in ("/mcp", "/workflows/recent"):
            header = request.headers.get("authorization", "")
            if not secrets.compare_digest(header, f"Bearer {api_token}"):
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32001, "message": "未授权：缺少或错误的 Bearer Token"}},
                    status_code=401)
            request.state.auth_identity = "authenticated"
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        payload: dict[str, Any] = {"status": "ok",
                                   "tools": len(registry.list_tools())}
        if adapters:
            payload["adapters"] = [
                {"name": kind, **adapter_health(ad)} for kind, ad in adapters]
        return payload

    @app.get("/workflows/recent")
    def workflows_recent() -> dict[str, Any]:
        if gateway.workflow is None:
            return {"items": []}
        return {"items": gateway.workflow.recent()}

    @app.post("/mcp")
    async def mcp(request: Request) -> JSONResponse:
        body = await request.json()
        method = body.get("method", "")
        params = body.get("params") or {}
        rpc_id = body.get("id")

        if method == "initialize":  # 兼容 2025-11-25 有状态客户端
            result = {"protocolVersion": "2025-11-25",
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "uniagent-hub", "version": "0.3.0"}}
        elif method == "ping":
            result = {}
        elif method == "server/discover":
            result = gateway.discover()
        elif method == "server/attestation":
            # 工具清单证明（改进方案 §5.1）：内容哈希 + 可选 Ed25519 签名
            result = gateway.attestation()
        elif method == "tools/list":
            result = gateway.list_tools()
        elif method == "tools/call":
            # P0-BE-1：认证身份由中间件写入 request.state，服务端据此裁决权限
            authenticated = bool(getattr(request.state, "auth_identity", None))
            result = gateway.call(params, authenticated=authenticated)
        else:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32601, "message": f"方法不存在: {method}"}},
                                status_code=400)
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    return app
