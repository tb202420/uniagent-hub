"""适配器插件（entry_points）与生命周期回调测试（改进方案 §4）。"""

import tempfile
from pathlib import Path

from core.adapters import plugins
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore


class _GoodPlugin:
    """合规插件：discover 注册一个平台工具 + 实现健康检查。"""

    def __init__(self, registry):
        self.registry = registry

    def discover(self):
        self.registry.register_tool("plugin_tool", {
            "name": "plugin_tool", "description": "插件工具",
            "inputSchema": {"type": "object", "properties": {}}})

    def on_health_check(self):
        return {"ok": True, "kind": "good"}


class _BadPlugin:
    """构造即失败的插件（验证加载失败不阻断启动）。"""

    def __init__(self, registry):
        raise RuntimeError("boom")


class _FakeEP:
    def __init__(self, name, obj):
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


def test_load_plugins_ok_and_failure(monkeypatch, tmp_path):
    eps = [_FakeEP("good", _GoodPlugin), _FakeEP("bad", _BadPlugin)]
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda group: eps)
    reg = ToolRegistry(SQLiteStore(tmp_path / "t.db"))
    results = plugins.load_adapter_plugins(reg)
    assert [r.name for r in results] == ["good", "bad"]
    assert results[0].loaded is True
    assert results[0].adapter is not None
    assert results[1].loaded is False
    assert "RuntimeError" in results[1].error
    assert "plugin_tool" in {t["name"] for t in reg.list_tools()}


def test_load_plugins_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(plugins, "_iter_entry_points", lambda group: [])
    reg = ToolRegistry(SQLiteStore(tmp_path / "t.db"))
    assert plugins.load_adapter_plugins(reg) == []


def test_lifecycle_defaults_and_error_isolation():
    class Bare:
        pass

    assert plugins.adapter_health(Bare()) == {"ok": True}
    plugins.adapter_startup(Bare())    # 无回调 → 无操作（不抛异常）
    plugins.adapter_shutdown(Bare())

    class Broken:
        def on_health_check(self):
            raise ValueError("x")

    health = plugins.adapter_health(Broken())
    assert health["ok"] is False
    assert "ValueError" in health["error"]


def test_lifecycle_callbacks_invoked():
    class Tracked:
        def __init__(self):
            self.started = 0
            self.stopped = 0

        def on_startup(self):
            self.started += 1

        def on_shutdown(self):
            self.stopped += 1

    t = Tracked()
    plugins.adapter_startup(t)
    plugins.adapter_shutdown(t)
    assert (t.started, t.stopped) == (1, 1)