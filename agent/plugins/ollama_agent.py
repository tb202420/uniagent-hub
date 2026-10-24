"""本地 Ollama Agent（内置插件 · 检测到服务时可用）。

原生 /api/chat tool_calls 闭环（对齐 agent/llm_agent.py 的实测经验）：
- temperature 0（数值保真，见研究报告 §5.7 温度实验）
- 串行执行：每轮至多执行一个 tool_call 并把结果回填，直到模型给出最终回答
- cancel 每轮检查；步数上限防失控
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import httpx

from agent.plugins.base import AgentAdapter

_MAX_STEPS = 8


class OllamaAgent(AgentAdapter):
    NAME = "ollama"

    def __init__(self) -> None:
        self.base = os.environ.get("OLLAMA_BASE", "http://localhost:11434").rstrip("/")
        self.model = os.environ.get("OLLAMA_MODEL", "gemma4local:latest")

    def health_check(self) -> dict[str, Any]:
        try:
            r = httpx.get(f"{self.base}/api/tags", timeout=2)
            ok = r.status_code == 200
            return {"ok": ok, "reason": "" if ok else f"HTTP {r.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"Ollama 不可达（{type(e).__name__}）"}

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base}/api/tags", timeout=2)
            return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:  # noqa: BLE001
            return []

    def run(self, goal: str, gateway_url: str = "http://127.0.0.1:8020",
            permission: str = "read",
            cancel: threading.Event | None = None) -> dict[str, Any]:
        if not self.health_check().get("ok"):
            return {"ok": False, "plan": {"kind": "llm"}, "steps": [],
                    "summary": "Ollama 未就绪（可回退 script 插件）"}
        headers = _hub_headers()
        with httpx.Client(timeout=120, headers=headers) as c:
            tools = _tools(c, gateway_url)
            messages = [
                {"role": "system", "content":
                 "你是温室与办公环境助手。只通过提供的工具行动；需要工具时一次只调用一个，"
                 "等待结果再继续。完成后用一句中文总结，并如实复述工具返回的数值。"},
                {"role": "user", "content": goal},
            ]
            steps: list[dict[str, Any]] = []
            for i in range(_MAX_STEPS):
                if cancel and cancel.is_set():
                    return {"ok": False, "plan": {"kind": "llm"}, "steps": steps,
                            "summary": "已取消"}
                r = c.post(f"{self.base}/api/chat", json={
                    "model": self.model, "messages": messages, "tools": tools,
                    "stream": False, "options": {"temperature": 0.0},
                }, timeout=120)
                msg = r.json().get("message", {})
                calls = msg.get("tool_calls") or []
                if not calls:
                    return {"ok": True, "plan": {"kind": "llm"}, "steps": steps,
                            "summary": (msg.get("content") or "")[:300]}
                call = calls[0]                       # 串行：一轮一个
                fn = (call.get("function") or {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                resp = _call(c, gateway_url, {"name": name, "arguments": args,
                                              "caller": "agent:ollama",
                                              "permission_level": permission})
                ok = not resp.get("isError")
                steps.append({"step": i + 1, "tool": name, "ok": ok,
                              "output": _text(resp)[:200]})
                messages.append(msg)
                messages.append({"role": "tool",
                                 "name": name,
                                 "content": _text(resp)[:2000]})
            return {"ok": False, "plan": {"kind": "llm"}, "steps": steps,
                    "summary": f"达到步数上限 {_MAX_STEPS}（未收敛）"}


def _hub_headers() -> dict[str, str]:
    token = os.environ.get("HUB_API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _tools(c: httpx.Client, base: str) -> list[dict[str, Any]]:
    r = c.post(f"{base.rstrip('/')}/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    out = []
    for t in r.json().get("result", {}).get("tools", []):
        out.append({"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("inputSchema", {"type": "object", "properties": {}})}})
    return out


def _call(c: httpx.Client, base: str, params: dict) -> dict[str, Any]:
    resp = c.post(f"{base.rstrip('/')}/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    return resp.json().get("result", {})


def _text(r: dict) -> str:
    return (r.get("content") or [{}])[0].get("text", "")
