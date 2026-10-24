"""OpenAI 兼容云模型 Agent（内置插件 · 配置 Key 后可用）。

环境变量：AGENT_OPENAI_BASE（默认 https://api.deepseek.com）/ AGENT_OPENAI_KEY /
AGENT_OPENAI_MODEL（默认 deepseek-chat）。走 /v1/chat/completions 的 tool_calls 闭环，
串行执行 + 温度 0 + 步数上限（与本地插件同约定）。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import httpx

from agent.plugins.base import AgentAdapter

_MAX_STEPS = 8


class OpenAICompatAgent(AgentAdapter):
    NAME = "openai-compat"

    def __init__(self) -> None:
        self.base = os.environ.get(
            "AGENT_OPENAI_BASE", "https://api.deepseek.com").rstrip("/")
        self.model = os.environ.get("AGENT_OPENAI_MODEL", "deepseek-chat")

    def _key(self) -> str:
        return os.environ.get("AGENT_OPENAI_KEY", "").strip()

    def health_check(self) -> dict[str, Any]:
        if not self._key():
            return {"ok": False, "reason": "未配置 AGENT_OPENAI_KEY"}
        try:
            r = httpx.get(f"{self.base}/v1/models", timeout=5,
                          headers={"Authorization": f"Bearer {self._key()}"})
            return {"ok": r.status_code == 200,
                    "reason": "" if r.status_code == 200 else f"HTTP {r.status_code}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"不可达（{type(e).__name__}）"}

    def list_models(self) -> list[str]:
        return [self.model]

    def run(self, goal: str, gateway_url: str = "http://127.0.0.1:8020",
            permission: str = "read",
            cancel: threading.Event | None = None) -> dict[str, Any]:
        if not self._key():
            return {"ok": False, "plan": {"kind": "llm-cloud"}, "steps": [],
                    "summary": "未配置 AGENT_OPENAI_KEY（可回退 script 插件）"}
        auth = {"Authorization": f"Bearer {self._key()}"}
        token = os.environ.get("HUB_API_TOKEN", "")
        if token:
            auth["Authorization_hub"] = ""   # 占位避免误用；Hub 头单独带
        hub_headers = ({"Authorization": f"Bearer {token}"} if token else {})
        with httpx.Client(timeout=60) as c:
            tools = _tools(c, gateway_url, hub_headers)
            messages = [
                {"role": "system", "content":
                 "你是环境助手。只通过工具行动，一次调用一个并等待结果；"
                 "完成后一句中文总结，数值必须来自工具返回。"},
                {"role": "user", "content": goal},
            ]
            steps: list[dict[str, Any]] = []
            for i in range(_MAX_STEPS):
                if cancel and cancel.is_set():
                    return {"ok": False, "plan": {"kind": "llm-cloud"},
                            "steps": steps, "summary": "已取消"}
                r = c.post(f"{self.base}/v1/chat/completions", headers=auth, json={
                    "model": self.model, "messages": messages, "tools": tools,
                    "temperature": 0.0,
                })
                choice = (r.json().get("choices") or [{}])[0]
                msg = choice.get("message", {})
                calls = msg.get("tool_calls") or []
                if not calls:
                    return {"ok": True, "plan": {"kind": "llm-cloud"},
                            "steps": steps,
                            "summary": (msg.get("content") or "")[:300]}
                call = calls[0]
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                resp = _call(c, gateway_url, {
                    "name": name, "arguments": args,
                    "caller": "agent:openai-compat",
                    "permission_level": permission}, hub_headers)
                ok = not resp.get("isError")
                steps.append({"step": i + 1, "tool": name, "ok": ok,
                              "output": _text(resp)[:200]})
                messages.append(msg)
                messages.append({"role": "tool", "tool_call_id":
                                 call.get("id", ""), "content": _text(resp)[:2000]})
            return {"ok": False, "plan": {"kind": "llm-cloud"}, "steps": steps,
                    "summary": f"达到步数上限 {_MAX_STEPS}（未收敛）"}


def _tools(c: httpx.Client, base: str, headers: dict) -> list[dict[str, Any]]:
    r = c.post(f"{base.rstrip('/')}/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    out = []
    for t in r.json().get("result", {}).get("tools", []):
        out.append({"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("inputSchema", {"type": "object", "properties": {}})}})
    return out


def _call(c: httpx.Client, base: str, params: dict,
          headers: dict) -> dict[str, Any]:
    resp = c.post(f"{base.rstrip('/')}/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    return resp.json().get("result", {})


def _text(r: dict) -> str:
    return (r.get("content") or [{}])[0].get("text", "")
