"""确定性脚本 Agent（内置插件 · 演示保底路径）。

规则式意图解析（零模型依赖）→ 经 Hub 网关执行：
- 浇灌类目标 → run_workflow（smart_irrigation / light_aware / dry_alert，可解析时长）
- 巡检/状态类 → office_status
- 其他 → 渐进式发现演示（discover_tools → get_tool_schema → execute_tool 元工具链）

任何一步都走 /mcp（Guard 管道 + 审计不旁路）。
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

import httpx

from agent.plugins.base import AgentAdapter


class ScriptAgent(AgentAdapter):
    NAME = "script"

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "reason": "确定性规则，无外部依赖"}

    def list_models(self) -> list[str]:
        return ["deterministic-script"]

    # ---- 意图解析（纯函数，供单元测试）----

    @staticmethod
    def plan_goal(goal: str) -> dict[str, Any]:
        g = goal.strip()
        if not g:
            return {"kind": "unknown", "reason": "空目标"}
        # 时长解析："浇 300 秒" / "浇3分钟" / 默认 300
        duration = 300
        m = re.search(r"(\d{1,4})\s*(秒|s)\b", g, re.I)
        if m:
            duration = min(600, max(1, int(m.group(1))))
        else:
            m = re.search(r"(\d{1,3})\s*分钟", g)
            if m:
                duration = min(600, max(1, int(m.group(1)) * 60))
        if any(k in g for k in ("土壤", "浇水", "灌溉", "泵")):
            if any(k in g for k in ("光照", "白天")):
                wf = "light_aware_irrigation"
            elif any(k in g for k in ("三次", "3 次", "连续", "告警")):
                wf = "dry_soil_alert_irrigation"
            else:
                wf = "smart_irrigation"
            return {"kind": "workflow", "workflow": wf, "params": {"duration": duration}}
        if any(k in g for k in ("降温", "空调", "太热")):
            return {"kind": "workflow", "workflow": "office_cooling", "params": {}}
        if any(k in g for k in ("巡检", "状态", "快照", "报告")):
            return {"kind": "workflow", "workflow": "office_status",
                    "params": {"dir": ".", "ext": "py"}}
        return {"kind": "discover", "query": g}

    # ---- 执行 ----

    def run(self, goal: str, gateway_url: str = "http://127.0.0.1:8020",
            permission: str = "read",
            cancel: threading.Event | None = None) -> dict[str, Any]:
        plan = self.plan_goal(goal)
        steps: list[dict[str, Any]] = []
        headers = _hub_headers()
        with httpx.Client(timeout=30, headers=headers) as c:
            if plan["kind"] == "workflow":
                if cancel and cancel.is_set():
                    return {"ok": False, "plan": plan, "steps": [],
                            "summary": "已取消"}
                steps.append({"step": "run_workflow", "input": plan["workflow"]})
                r = _call(c, gateway_url, {
                    "name": "run_workflow",
                    "arguments": {"workflow": plan["workflow"],
                                  "params": plan.get("params", {})},
                    "caller": "agent:script", "permission_level": "write"})
                ok = not r.get("isError")
                steps.append({"step": plan["workflow"], "ok": ok,
                              "output": _text(r)[:400]})
                return {"ok": ok, "plan": plan, "steps": steps,
                        "summary": _text(r)[:200]}
            # 渐进式发现演示链
            r1 = _meta(c, gateway_url, "discover_tools", {"query": ""})
            steps.append({"step": "discover_tools", "ok": not r1.get("isError"),
                          "output": _text(r1)[:300]})
            if cancel and cancel.is_set():
                return {"ok": False, "plan": plan, "steps": steps,
                        "summary": "已取消"}
            r2 = _meta(c, gateway_url, "get_tool_schema",
                       {"name": plan["query"][:32]})
            found = not r2.get("isError")
            steps.append({"step": "get_tool_schema", "ok": found,
                          "output": _text(r2)[:300]})
            if not found:
                return {"ok": False, "plan": plan, "steps": steps,
                        "summary": f"未找到匹配工具：{plan['query'][:40]}"}
            name = json.loads(_text(r2)).get("name", "")
            r3 = _meta(c, gateway_url, "execute_tool",
                       {"tool": name, "arguments": {}})
            ok = not r3.get("isError")
            steps.append({"step": f"execute_tool:{name}", "ok": ok,
                          "output": _text(r3)[:300]})
            return {"ok": ok, "plan": plan, "steps": steps,
                    "summary": _text(r3)[:200]}


def _hub_headers() -> dict[str, str]:
    token = os.environ.get("HUB_API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _call(c: httpx.Client, base: str, params: dict) -> dict[str, Any]:
    resp = c.post(f"{base.rstrip('/')}/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    return resp.json().get("result", {})


def _meta(c: httpx.Client, base: str, name: str, args: dict) -> dict[str, Any]:
    return _call(c, base, {"name": name, "arguments": args,
                           "caller": "agent:script", "permission_level": "read"})


def _text(r: dict) -> str:
    return (r.get("content") or [{}])[0].get("text", "")
