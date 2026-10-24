"""Agent 插件宿主测试：注册表发现 / 脚本意图解析 / 执行链 / 未就绪降级。"""

import threading
from unittest import mock

import agent.plugins.registry as reg_mod
from agent.plugins.openai_compat import OpenAICompatAgent
from agent.plugins.ollama_agent import OllamaAgent
from agent.plugins.registry import agent_statuses, load_agent_plugins
from agent.plugins.script_agent import ScriptAgent


def test_builtin_agents_discovered():
    agents = load_agent_plugins()
    assert {"script", "ollama", "openai-compat"} <= set(agents)


def test_entry_point_third_party_plugin(monkeypatch):
    class _ThirdParty:
        NAME = "third"

        def health_check(self):
            return {"ok": True}

        def list_models(self):
            return ["x"]

        def run(self, goal, gateway_url="http://x", permission="read",
                cancel=None):
            return {"ok": True, "plan": {}, "steps": [], "summary": "third"}

    class _EP:
        name = "third"

        @staticmethod
        def load():
            return _ThirdParty

    monkeypatch.setattr(reg_mod, "entry_points",
                        lambda group: [_EP()] if group == reg_mod.PLUGIN_GROUP else [])
    agents = load_agent_plugins()
    assert agents["third"].NAME == "third"


def test_statuses_mark_unready():
    st = {s["name"]: s for s in agent_statuses(load_agent_plugins())}
    assert st["script"]["ok"] is True                       # 零依赖恒就绪
    assert st["openai-compat"]["ok"] is False               # 未配 Key
    assert "reason" in st["openai-compat"]


# ---- 脚本 Agent 意图解析（纯函数）----

def test_plan_irrigation_with_duration():
    p = ScriptAgent.plan_goal("土壤湿度低于30%就浇水300秒")
    assert p["kind"] == "workflow"
    assert p["workflow"] == "smart_irrigation"
    assert p["params"]["duration"] == 300


def test_plan_irrigation_minutes_clamped():
    p = ScriptAgent.plan_goal("连续三次土壤太干就浇水 20 分钟")
    assert p["workflow"] == "dry_soil_alert_irrigation"
    assert p["params"]["duration"] == 600                   # 1200s → 钳位 600


def test_plan_light_aware_and_cooling_and_snapshot():
    assert ScriptAgent.plan_goal("白天光照够再浇水")["workflow"] == "light_aware_irrigation"
    assert ScriptAgent.plan_goal("会议室太热了降温")["workflow"] == "office_cooling"
    assert ScriptAgent.plan_goal("做个环境巡检")["workflow"] == "office_status"
    assert ScriptAgent.plan_goal("随便看看有什么工具")["kind"] == "discover"


def test_plan_empty_goal():
    assert ScriptAgent.plan_goal("  ")["kind"] == "unknown"


# ---- 执行链（打桩 httpx，验证走 /mcp + 权限字段）----

def test_script_agent_run_workflow_path(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"result": {"content": [{"type": "text",
                                            "text": '{"ok": true}'}],
                               "isError": False}}

    def fake_post(self, url, json=None, **_kw):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr("httpx.Client.post", fake_post)
    out = ScriptAgent().run("土壤干了浇水300秒",
                            gateway_url="http://127.0.0.1:8020")
    assert captured["url"].endswith("/mcp")
    assert captured["json"]["params"]["name"] == "run_workflow"
    assert captured["json"]["params"]["caller"] == "agent:script"
    assert out["ok"] is True and len(out["steps"]) == 2


def test_script_agent_cancel_before_run():
    ev = threading.Event()
    ev.set()
    out = ScriptAgent().run("浇水", gateway_url="http://127.0.0.1:8020", cancel=ev)
    assert out["ok"] is False and out["summary"] == "已取消"


def test_ollama_agent_not_ready(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE", "http://127.0.0.1:1")   # 不可达端口
    out = OllamaAgent().run("查温度")
    assert out["ok"] is False and "未就绪" in out["summary"]


def test_openai_agent_requires_key(monkeypatch):
    monkeypatch.delenv("AGENT_OPENAI_KEY", raising=False)
    assert OpenAICompatAgent().health_check()["ok"] is False
    out = OpenAICompatAgent().run("查温度")
    assert out["ok"] is False
