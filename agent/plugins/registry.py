"""Agent 插件注册表：内置适配器 + entry_points 第三方发现（组 uniagent_hub.agent_adapters）。"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from agent.plugins.base import AgentAdapter
from agent.plugins.ollama_agent import OllamaAgent
from agent.plugins.openai_compat import OpenAICompatAgent
from agent.plugins.script_agent import ScriptAgent

PLUGIN_GROUP = "uniagent_hub.agent_adapters"


def _builtins() -> list[AgentAdapter]:
    return [ScriptAgent(), OllamaAgent(), OpenAICompatAgent()]


def load_agent_plugins(group: str = PLUGIN_GROUP) -> dict[str, AgentAdapter]:
    """内置插件 + entry_points 第三方插件（加载失败不阻断，记录错误）。"""
    agents: dict[str, AgentAdapter] = {}
    for adapter in _builtins():
        agents[adapter.NAME] = adapter
    try:
        for ep in entry_points(group=group):
            try:
                cls = ep.load()
                adapter = cls()
                agents[adapter.NAME] = adapter
                print(f"[agent_host] 已加载 Agent 插件: {ep.name} -> {cls.__name__}")
            except Exception as e:  # noqa: BLE001 - 单个插件失败不阻断
                print(f"[agent_host] Agent 插件加载失败 {ep.name}: {e}")
    except Exception:  # noqa: BLE001 - entry_points 机制异常时仅内置可用
        pass
    return agents


def agent_statuses(agents: dict[str, AgentAdapter] | None = None) -> list[dict[str, Any]]:
    """全部插件的就绪状态与模型（供 CLI / 界面展示）。"""
    agents = agents if agents is not None else load_agent_plugins()
    out = []
    for name, a in agents.items():
        try:
            health = a.health_check()
        except Exception as e:  # noqa: BLE001
            health = {"ok": False, "reason": f"{type(e).__name__}: {e}"}
        item = {"name": name, "ok": bool(health.get("ok")),
                "models": health.get("ok") and _safe_models(a) or []}
        if not health.get("ok"):
            item["reason"] = health.get("reason", "未就绪")
        out.append(item)
    return out


def _safe_models(a: AgentAdapter) -> list[str]:
    try:
        return a.list_models()
    except Exception:  # noqa: BLE001
        return []
