"""渐进式工具发现 Meta-Tools（改进方案 §3）。

把"一次性返回全部工具 Schema"改为 **4 个元工具**，Agent 按需加载具体工具签名，
在工具数量增长（50+/100+）时显著降低上下文占用：

  discover_tools    浏览工具域与数量；按 domain 或 query 查询
  get_tool_schema   获取指定工具的完整 JSON Schema（支持模糊匹配）
  execute_tool      路由执行任意工具（**经网关 Guard 管道，安全不旁路**）
  refresh_registry  重新查询注册表，返回新增/移除工具摘要

启用方式：``HUB_META_TOOLS=1`` 或 ``python main.py --meta-tools``（默认关闭，
保持全量列表模式，演示链路不受影响）。自研网关与 FastMCP 前端共用本模块。
"""

from __future__ import annotations

import json
from typing import Any

from core.contracts import (
    CallContext, ToolResult, E_INVALID_ARGS, E_TOOL_NOT_FOUND,
)

# 工具域划分（按 UniSpec type；run_workflow 等平台虚拟工具归入 workflow）
_DOMAIN_DESC = {
    "iot": "物联网设备（MQTT 自动发现 + 状态缓存）",
    "cli": "命令行工具（subprocess 沙箱）",
    "rest": "REST API（OpenAPI 导入）",
    "script": "本地脚本（路径沙箱）",
    "database": "数据库（SQLite 只读查询 / 受限写）",
    "workflow": "工作流编排（预定义蓝图）",
}
_TYPE_DOMAIN = {
    "iot_device": "iot",
    "cli_tool": "cli",
    "rest_api": "rest",
    "local_script": "script",
    "database": "database",
}
_META_NAMES = ("discover_tools", "get_tool_schema", "execute_tool", "refresh_registry")


def _fuzzy_match(query: str, candidates: list[str]) -> list[str]:
    """模糊匹配：精确 > 子串 > 子序列（如 gitst → git_status）。"""
    q = query.strip().lower()
    if not q:
        return []
    exact = [c for c in candidates if c.lower() == q]
    if exact:
        return exact
    subs = [c for c in candidates if q in c.lower()]
    if subs:
        return subs
    seq: list[str] = []
    for c in candidates:
        it = iter(c.lower())
        if all(ch in it for ch in q):
            seq.append(c)
    return seq


class MetaTools:
    """4 个元工具的实现（供自研网关与 FastMCP 前端共用）。"""

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway
        self._snapshot: set[str] | None = None

    # ---- 定义 ----

    def handles(self, name: str) -> bool:
        return name in _META_NAMES

    def definitions(self) -> list[dict]:
        """4 个元工具的 MCP Tool 定义（meta 模式下 tools/list 返回这些）。"""
        return [
            {
                "name": "discover_tools",
                "title": "发现工具",
                "description": "浏览工具域与数量；按 domain 查看某域工具，或按 query 关键词搜索",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "enum": sorted(_DOMAIN_DESC)},
                        # 允许中文等自然语言关键词；仅拦截 shell 元字符
                        "query": {"type": "string",
                                  "pattern": "^[^;&|`$<>\\\\'\"]+$"},
                    },
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "get_tool_schema",
                "title": "获取工具 Schema",
                "description": "按名称（支持模糊匹配）获取工具的完整 JSON Schema",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "pattern": "^[a-zA-Z0-9_.-]+$"},
                    },
                    "required": ["name"],
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "execute_tool",
                "title": "执行工具",
                "description": "路由并执行任意已发现的工具（完整走 Guard 安全管道）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string",
                                 "pattern": "^[a-z][a-zA-Z0-9_]*$"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool"],
                },
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "refresh_registry",
                "title": "刷新注册表",
                "description": "重新查询注册表，返回自上次查询以来新增/移除的工具摘要",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True},
            },
        ]

    def schema_of(self, name: str) -> dict:
        for t in self.definitions():
            if t["name"] == name:
                return t["inputSchema"]
        return {}

    # ---- 目录（catalog）----

    def catalog(self) -> list[dict]:
        """全部工具目录：[{name, domain, description}]（含 run_workflow）。"""
        items: list[dict] = []
        for tool in self.gateway.registry.list_tools():
            name = tool["name"]
            resolved = self.gateway.registry.resolve(name)
            domain = _TYPE_DOMAIN.get(resolved[0].type, "workflow") if resolved else "workflow"
            items.append({"name": name, "domain": domain,
                          "description": tool.get("description", "")})
        return items

    # ---- 分发（自研网关调用）----

    def dispatch(self, name: str, args: dict) -> ToolResult:
        """执行非 execute_tool 的三个元工具（execute_tool 由网关特殊处理）。"""
        if name == "discover_tools":
            return self._discover(args)
        if name == "get_tool_schema":
            return self._get_schema(args)
        if name == "refresh_registry":
            return self._refresh()
        return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                          error_msg=f"元工具不存在: {name}")

    def execute(self, target: str, arguments: dict, ctx: CallContext) -> dict:
        """执行目标工具：透传网关完整调用链（含 Guard 校验 / 限流 / 审计）。

        返回网关标准响应结构（与 tools/call 一致）；目标不存在/被拦截等
        错误码原样透传（1001/1002/1003/1004/1007...）。

        internal=True：本中继的 ctx 已由外层调用经 Guard 裁决（鉴权模式下
        permission_level 是服务端派生值，非客户端自报）；目标工具仍完整走
        Guard 管道（存在性/限流/参数校验/审计不旁路）。未启用鉴权时该分支
        与历史行为逐字段一致。
        """
        return self.gateway.call({
            "name": target,
            "arguments": arguments,
            "caller": ctx.caller,
            "trace_id": ctx.trace_id,
            "permission_level": ctx.permission_level,
        }, internal=True)

    # ---- 各元工具实现 ----

    def _discover(self, args: dict) -> ToolResult:
        domain = (args.get("domain") or "").strip()
        query = (args.get("query") or "").strip()
        items = self.catalog()

        if query:
            names = [i["name"] for i in items]
            hits = _fuzzy_match(query, names)
            matched = [i for i in items if i["name"] in hits]
            return ToolResult(ok=True, data=json.dumps(
                {"query": query, "count": len(matched), "tools": matched},
                ensure_ascii=False))

        if domain:
            if domain not in _DOMAIN_DESC:
                return ToolResult(
                    ok=False, error_code=E_INVALID_ARGS,
                    error_msg=f"未知工具域 {domain!r}，可用: {sorted(_DOMAIN_DESC)}")
            matched = [i for i in items if i["domain"] == domain]
            return ToolResult(ok=True, data=json.dumps(
                {"domain": domain, "count": len(matched), "tools": matched},
                ensure_ascii=False))

        # 无过滤：域汇总（含前 3 个样例工具名）
        summary = []
        for dname, ddesc in sorted(_DOMAIN_DESC.items()):
            tools = [i["name"] for i in items if i["domain"] == dname]
            summary.append({"domain": dname, "description": ddesc,
                            "count": len(tools), "sample": tools[:3]})
        return ToolResult(ok=True, data=json.dumps(
            {"total": len(items), "domains": summary,
             "hint": "使用 domain 或 query 参数查看具体工具签名"},
            ensure_ascii=False))

    def _get_schema(self, args: dict) -> ToolResult:
        name = (args.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error_code=E_INVALID_ARGS,
                              error_msg="缺少参数: name")
        tools = {t["name"]: t for t in self.gateway.registry.list_tools()}
        candidates = _fuzzy_match(name, list(tools))
        if len(candidates) == 1:
            return ToolResult(ok=True, data=json.dumps(
                tools[candidates[0]], ensure_ascii=False))
        if not candidates:
            return ToolResult(
                ok=False, error_code=E_TOOL_NOT_FOUND,
                error_msg=f"未找到工具 {name!r}（可用: {list(tools)[:8]} …）")
        return ToolResult(ok=True, data=json.dumps(
            {"ambiguous": True, "candidates": candidates,
             "hint": "名称不唯一，请用完整工具名重新查询"},
            ensure_ascii=False))

    def _refresh(self) -> ToolResult:
        current = {i["name"] for i in self.catalog()}
        added = sorted(current - (self._snapshot or set()))
        removed = sorted((self._snapshot or set()) - current) if self._snapshot else []
        self._snapshot = current
        return ToolResult(ok=True, data=json.dumps(
            {"total": len(current), "added": added, "removed": removed},
            ensure_ascii=False))