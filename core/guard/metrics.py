"""Prometheus 指标（v2.0 §3.11 可观测层，轻量落地）。

指标（在 Gateway _finish 处埋点，与审计同源，不旁路）：
  uniagent_tool_calls_total{tool, result=ok|blocked}   调用计数
  uniagent_guard_blocked_total{error_code}             拦截计数（1003/1004/1007…）
  uniagent_tool_latency_seconds{tool}                  延迟直方图
  uniagent_workflow_runs_total{workflow, result}       工作流计数

软依赖：prometheus_client 未安装时全部为 no-op（/metrics 返回 503 提示），
核心链路零依赖；requirements 已锁定版本。
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Counter, Histogram, generate_latest
    _ENABLED = True
except ImportError:  # pragma: no cover - 软依赖路径
    _ENABLED = False

_m: dict[str, Any] = {}


def _init() -> None:
    if not _ENABLED or _m:
        return
    _m["calls"] = Counter("uniagent_tool_calls_total",
                          "工具调用总数", ["tool", "result"])
    _m["blocked"] = Counter("uniagent_guard_blocked_total",
                            "Guard 拦截总数", ["error_code"])
    _m["latency"] = Histogram(
        "uniagent_tool_latency_seconds", "工具调用延迟（秒）", ["tool"],
        buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
    _m["wf"] = Counter("uniagent_workflow_runs_total",
                       "工作流执行总数", ["workflow", "result"])


def observe_call(tool: str, ok: bool, error_code: int,
                 latency_ms: float) -> None:
    _init()
    if not _ENABLED:
        return
    _m["calls"].labels(tool=tool, result="ok" if ok else "blocked").inc()
    if not ok and error_code:
        _m["blocked"].labels(error_code=error_code).inc()
    if ok:
        _m["latency"].labels(tool=tool).observe(max(0.0, latency_ms) / 1000.0)


def observe_workflow(name: str, ok: bool) -> None:
    _init()
    if _ENABLED:
        _m["wf"].labels(workflow=name, result="ok" if ok else "error").inc()


def render() -> bytes | None:
    """Prometheus 文本格式；未安装依赖时返回 None。"""
    _init()
    if not _ENABLED:
        return None
    return generate_latest()
