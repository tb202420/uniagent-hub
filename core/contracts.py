"""跨模块共享契约（docs/api.md §3 冻结，勿改签名）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CallContext:
    """一次 tools/call 的上下文，贯穿 Guard → 适配器 → 审计。"""

    trace_id: str
    caller: str = "unknown"
    permission_level: str = "read"  # read | write | admin


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error_code: int = 0
    error_msg: str = ""
    latency_ms: int = 0


class BaseAdapter(Protocol):
    """适配器统一协议（docs/api.md §3）。"""

    def discover(self) -> list[dict]:
        """返回该适配器管理的全部 UniSpec 描述。"""

    def list_tools(self) -> list[dict]:
        """返回 MCP Tool 定义列表。"""

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        """执行工具调用。必须：先校验参数、记录 trace_id、返回结构化结果。"""


# 错误码（docs/api.md §4 冻结）
E_OK = 0
E_TOOL_NOT_FOUND = 1001
E_INVALID_ARGS = 1002
E_PERMISSION_DENIED = 1003
E_RATE_LIMITED = 1004
E_TIMEOUT = 1005
E_RESOURCE_UNAVAILABLE = 1006
E_INJECTION_BLOCKED = 1007
E_INTERNAL = 1999
