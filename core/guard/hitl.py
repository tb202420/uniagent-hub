"""HITL 审批（Human-in-the-Loop，v3.0）。

与 Guard 管道的关系：
  只读调用 → 权限校验 → 自动放行（不变）
  写入调用 → 权限校验 → **审批闸门（本模块）** → 批准后执行 / 拒绝即返回
  高风险调用 → 审批 + 决策写入审计哈希链（批准/拒绝/超时全部留痕）

冻结约束：
- 不新增错误码。审批拒绝/超时复用 1003（E_PERMISSION_DENIED），
  api.md 错误码表 1001~1007/1999 保持冻结。
- 审批粒度克制：默认只对 control_pump 一个 write 工具触发
  （HUB_APPROVAL_TOOLS 可配置，逗号/分号分隔；"*" 表示全部 write/admin）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.gateway.event_bus import EventBus, default_bus

APPROVED = "approved"
REJECTED = "rejected"
TIMEOUT = "timeout"
PENDING = "pending"

# 工具 → 人类可读动作（审批卡片文案；未知工具回退通用句式）
_ACTION_TEXT = {
    "control_pump": "启动水泵",
    "ac_control": "调节空调",
    "plug_set_power": "切换智能插座电源",
    "db_execute": "执行数据库写操作",
    "run_workflow": "运行工作流",
}


def _env_list(name: str, default: str) -> set[str]:
    raw = os.environ.get(name, default)
    return {x.strip() for x in raw.replace(";", ",").split(",") if x.strip()}


def describe_tool(tool: str, args: dict[str, Any]) -> str:
    """审批卡片自然语言描述（v3.0 §第三阶段文案要求）。"""
    action = _ACTION_TEXT.get(tool, f"执行 {tool}")
    if tool == "control_pump":
        if str(args.get("action", "")).lower() == "off":
            return "AI 想关闭水泵，是否允许？"
        duration = args.get("duration")
        return (f"AI 想启动水泵 {duration} 秒，是否允许？"
                if duration not in (None, "") else "AI 想启动水泵，是否允许？")
    if tool == "db_execute":
        sql = str(args.get("sql", ""))[:80]
        return f"AI 想执行数据库写操作：{sql}，是否允许？"
    if tool == "ac_control":
        return f"AI 想调节空调（{json.dumps(args, ensure_ascii=False)}），是否允许？"
    return f"AI 想{action}（参数 {json.dumps(args, ensure_ascii=False)[:120]}），是否允许？"


def approval_options(tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    """审批卡片三操作（允许 / 拒绝 / 改成 60 秒）。"""
    options: list[dict[str, Any]] = [
        {"key": "approve", "label": "允许"},
        {"key": "reject", "label": "拒绝"},
    ]
    if tool == "control_pump" and str(args.get("action", "on")).lower() == "on":
        options.append({"key": "modify", "label": "改成 60 秒",
                        "override_args": {"action": "on", "duration": 60}})
    return options


@dataclass
class ApprovalRequest:
    id: str
    tool: str
    args: dict[str, Any]
    trace_id: str
    caller: str
    required_level: str
    summary: str
    options: list[dict[str, Any]]
    created_ts: float = field(default_factory=time.time)
    state: str = PENDING
    decision: str = ""
    decided_by: str = ""
    decided_ts: float | None = None
    override_args: dict[str, Any] | None = None
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.id, "tool": self.tool,
            "args": dict(self.args), "trace_id": self.trace_id,
            "caller": self.caller, "required_level": self.required_level,
            "summary": self.summary, "options": list(self.options),
            "created_ts": round(self.created_ts, 3), "state": self.state,
            "decision": self.decision, "decided_by": self.decided_by,
            "decided_ts": round(self.decided_ts, 3) if self.decided_ts else None,
            "override_args": self.override_args,
        }


class ApprovalBroker:
    def __init__(self, tools: set[str] | None = None,
                 timeout: float | None = None,
                 bus: EventBus | None = None,
                 audit: Any | None = None) -> None:
        self.tools = tools if tools is not None else _env_list(
            "HUB_APPROVAL_TOOLS", "control_pump")
        self.timeout = (timeout if timeout is not None else
                        float(os.environ.get("HUB_APPROVAL_TIMEOUT", "90")))
        self.bus = bus or default_bus
        self.audit = audit
        self._lock = threading.Lock()
        self._requests: dict[str, ApprovalRequest] = {}

    # ---- 判定 ----

    def requires(self, tool: str, cap: Any, level: str) -> bool:
        """是否触发审批：只对配置内的 write/admin 工具，只读永不触发。"""
        if getattr(cap, "readOnly", False):
            return False
        if level not in ("write", "admin"):
            return False
        if "*" in self.tools:
            return True
        return tool in self.tools

    # ---- 请求 / 等待 / 决策 ----

    def request(self, *, tool: str, args: dict[str, Any], trace_id: str,
                caller: str, required_level: str) -> ApprovalRequest:
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:8], tool=tool, args=dict(args),
            trace_id=trace_id, caller=caller, required_level=required_level,
            summary=describe_tool(tool, args),
            options=approval_options(tool, args))
        with self._lock:
            self._requests[req.id] = req
        self.bus.publish("hitl.request", approval=req.to_dict())
        return req

    def wait(self, req: ApprovalRequest, timeout: float | None = None) -> dict[str, Any]:
        """阻塞等待人工决策（调用方必须运行在线程池/独立线程，不能占事件循环）。"""
        decided = req._event.wait(timeout if timeout is not None else self.timeout)
        with self._lock:
            if not decided and req.state == PENDING:
                req.state = TIMEOUT
                req.decision = TIMEOUT
                req.decided_ts = time.time()
        self._record_audit(req)
        self.bus.publish("hitl.decision", approval=req.to_dict())
        return req.to_dict()

    def decide(self, approval_id: str, decision: str, *,
               override_args: dict[str, Any] | None = None,
               decided_by: str = "spa") -> dict[str, Any]:
        if decision not in (APPROVED, REJECTED, "modify"):
            raise ValueError(f"未知审批决策: {decision!r}")
        with self._lock:
            req = self._requests.get(approval_id)
            if req is None:
                raise KeyError(f"审批请求不存在: {approval_id}")
            if req.state != PENDING:
                return req.to_dict()   # 幂等：已决策返回现状
            req.state = APPROVED if decision != REJECTED else REJECTED
            req.decision = decision
            req.decided_by = decided_by
            req.decided_ts = time.time()
            if decision == "modify":
                req.override_args = dict(override_args or {})
        req._event.set()
        return req.to_dict()

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._requests.values()
                    if r.state == PENDING]

    def get(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            req = self._requests.get(approval_id)
            return req.to_dict() if req else None

    def cancel_all(self) -> None:
        with self._lock:
            for req in self._requests.values():
                if req.state == PENDING:
                    req.state = TIMEOUT
                    req.decision = TIMEOUT
                    req.decided_ts = time.time()
                    req._event.set()

    # ---- 审计（写入哈希链）----

    def _record_audit(self, req: ApprovalRequest) -> None:
        if self.audit is None:
            return
        try:
            self.audit.record(
                trace_id=req.trace_id, caller=f"hitl:{req.decided_by or 'system'}",
                tool="hitl.approval",
                args={"approval_id": req.id, "target_tool": req.tool,
                      "target_args": req.args, "decision": req.decision,
                      "override_args": req.override_args},
                guard_result=("passed" if req.decision in (APPROVED, "modify")
                              else "blocked"),
                block_reason=("" if req.decision in (APPROVED, "modify")
                              else f"审批结果: {req.decision}"),
                result={"ok": req.decision in (APPROVED, "modify")},
                latency_ms=int((req.decided_ts - req.created_ts) * 1000)
                if req.decided_ts else 0,
                error_code=(0 if req.decision in (APPROVED, "modify") else 1003),
            )
        except Exception:  # noqa: BLE001 - 审计失败不阻断审批主链路
            pass
