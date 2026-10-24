"""AgentAdapter 统一接口（v2.0 §3.3）。

约定：
- health_check()  就绪检查（未就绪的插件不出现在可选列表，Hub 启动不受影响）
- list_models()   可用模型（脚本 Agent 返回 ["deterministic-script"]）
- run(goal)       执行一条自然语言目标：经 Hub 网关调用工具（Guard 不旁路），
                  返回 {"ok", "plan", "steps", "summary"}
- cancel          threading.Event；长循环每步检查，置位后优雅停止并如实标注

安全：所有工具调用都走 Hub 网关（tools/call / 元工具），权限与审计由 Guard 裁决；
本宿主不直连任何设备。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any


class AgentAdapter(ABC):
    """Agent 平台适配器基类（第三方插件继承并声明 NAME 类属性）。"""

    NAME: str = "agent"

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """返回 {"ok": bool, "reason"?: str}。"""

    @abstractmethod
    def list_models(self) -> list[str]:
        """可用模型名列表。"""

    @abstractmethod
    def run(self, goal: str, gateway_url: str = "http://127.0.0.1:8020",
            permission: str = "read",
            cancel: threading.Event | None = None) -> dict[str, Any]:
        """执行目标。cancel 置位后尽快返回 {"ok": False, "summary": "已取消"}。"""
