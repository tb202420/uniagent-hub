"""适配器插件发现与生命周期助手（改进方案 §4）。

- **entry_points 自动发现**：第三方适配器包在 `uniagent_hub.adapters` 组下声明入口点，
  Hub 启动时自动加载，核心代码零改动（``pyproject.toml`` 示例见 docs/design/improvement_plan.md）：
      [project.entry-points."uniagent_hub.adapters"]
      mqtt = "uniagent_hub_mqtt:MqttAdapter"

- **生命周期回调**（在统一三方法协议之上的可选扩展）：
      on_startup()         启动时初始化（连接池/预热）
      on_health_check()    健康检查（/healthz 汇总）
      on_shutdown()        优雅关闭
  采用鸭子类型调用：未实现回调的适配器自动跳过，保持向后兼容。
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Callable

PLUGIN_GROUP = "uniagent_hub.adapters"


@dataclass
class PluginResult:
    """单个插件的加载结果。"""

    name: str
    loaded: bool
    adapter: Any = None
    error: str = ""


def _iter_entry_points(group: str) -> list:
    """可注入的入口点迭代器（测试用 monkeypatch 替换）。"""
    return list(entry_points(group=group))


def load_adapter_plugins(registry: Any, *, group: str = PLUGIN_GROUP,
                         discover: Callable[[Any], Any] | None = None) -> list[PluginResult]:
    """加载第三方适配器插件：实例化 → discover() 注册工具。

    插件类约定 ``cls(registry)`` 构造，实现 ``discover()/list_tools()/call_tool()``
    （可选实现生命周期回调）。**加载失败不阻断 Hub 启动**：记录错误并继续。
    """
    results: list[PluginResult] = []
    for ep in _iter_entry_points(group):
        try:
            cls = ep.load()
            adapter = cls(registry)
            runner = discover or (lambda a: a.discover())
            runner(adapter)
            results.append(PluginResult(ep.name, True, adapter))
            print(f"[plugins] 已加载适配器插件: {ep.name} -> "
                  f"{getattr(cls, '__name__', cls)}")
        except Exception as e:  # noqa: BLE001 - 插件问题不应阻断 Hub
            results.append(PluginResult(ep.name, False, None,
                                        f"{type(e).__name__}: {e}"))
            print(f"[plugins] 插件加载失败: {ep.name}: {e}")
    return results


# ---- 生命周期回调（鸭子类型；未实现 = 无操作/视为健康）----

def adapter_startup(adapter: Any) -> None:
    """调用适配器 on_startup（若实现）。异常向上抛出（启动期问题应显式暴露）。"""
    fn = getattr(adapter, "on_startup", None)
    if callable(fn):
        fn()


def adapter_health(adapter: Any) -> dict:
    """调用适配器 on_health_check（若实现），统一返回 dict；异常降级为 ok=False。"""
    fn = getattr(adapter, "on_health_check", None)
    if callable(fn):
        try:
            return dict(fn())
        except Exception as e:  # noqa: BLE001 - 健康检查不应拖垮 /healthz
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True}


def adapter_shutdown(adapter: Any) -> None:
    """调用适配器 on_shutdown（若实现）；异常仅告警。"""
    fn = getattr(adapter, "on_shutdown", None)
    if callable(fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"[plugins] 适配器关闭异常: {type(e).__name__}: {e}")