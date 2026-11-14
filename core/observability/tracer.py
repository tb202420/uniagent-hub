"""OTel GenAI SemConv 兼容的追踪记录器（v3.0）。

为什么自研记录器：
- `/traces` 与前端瀑布图需要**进程内可查询的 span 树**，而 OTel SDK 的
  默认导出目标是 Collector（演示环境不保证有 Collector）。
- 本模块以 OTel GenAI SemConv 的**字段名**为契约（gen_ai.system /
  gen_ai.request.model / gen_ai.usage.input_tokens / output_tokens /
  gen_ai.response.finish_reasons），同时把 span 双写到 OTel SDK（可用时），
  因此"标准可依"与"演示可看"两件事同时成立。

诚实边界：
- 未安装 opentelemetry-sdk 时，仅本记录器工作（字段语义不变）；
- 未配置 HUB_OTEL_ENDPOINT 时，OTel SDK 用无导出器的 Provider（不发网络包）；
- 本记录器不是 OTel Collector 的替代品，只是可查询的本地 span 存储。
"""

from __future__ import annotations

import contextvars
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from core.gateway.event_bus import EventBus, default_bus

# ---- OTel GenAI SemConv 字段名（契约常量）----
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_FINISH_REASONS = "gen_ai.response.finish_reasons"

_current_span: contextvars.ContextVar["Span | None"] = contextvars.ContextVar(
    "uniagent_current_span", default=None)


@dataclass
class Span:
    trace_id: str
    span_id: str
    name: str
    kind: str
    start_ts: float
    parent_id: str | None = None
    end_ts: float | None = None
    status: str = "running"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        end = self.end_ts if self.end_ts is not None else time.time()
        return round((end - self.start_ts) * 1000, 2)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, **payload: Any) -> None:
        self.events.append({"name": name, "ts": round(time.time(), 4), **payload})

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "start_ts": round(self.start_ts, 4),
            "end_ts": round(self.end_ts, 4) if self.end_ts else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": dict(self.attributes),
            "events": list(self.events),
        }


class SpanHandle:
    """span 上下文管理器：with tracer.span(...) as s: ..."""

    def __init__(self, tracer: "Tracer", span: Span) -> None:
        self.tracer = tracer
        self.span = span
        self._token: contextvars.Token | None = None

    def __enter__(self) -> Span:
        self._token = _current_span.set(self.span)
        return self.span

    def set_attribute(self, key: str, value: Any) -> None:
        self.span.attributes[key] = value

    def add_event(self, name: str, **payload: Any) -> None:
        self.span.events.append({"name": name, "ts": round(time.time(), 4), **payload})

    def end(self, status: str = "ok", attributes: dict[str, Any] | None = None) -> Span:
        if attributes:
            self.span.attributes.update(attributes)
        self.span.status = status
        self.span.end_ts = time.time()
        self.tracer._finish(self.span)
        if self._token is not None:
            _current_span.reset(self._token)
            self._token = None
        return self.span

    def __exit__(self, exc_type, exc, tb) -> None:
        self.end(status="error" if exc_type else "ok",
                 attributes=({"error": f"{exc_type.__name__}: {exc}"}
                             if exc_type else None))


class Tracer:
    def __init__(self, bus: EventBus | None = None, max_traces: int = 120) -> None:
        self.bus = bus or default_bus
        self._lock = threading.Lock()
        self._spans: dict[str, Span] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._order: deque[str] = deque(maxlen=max_traces)
        self._otel_spans: dict[str, Any] = {}
        self._otel = self._init_otel()

    # ---- OTel SDK（可选）----

    @staticmethod
    def _init_otel() -> Any:
        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except Exception:  # noqa: BLE001 - 软依赖，未安装时纯本地记录
            return None
        try:
            provider = TracerProvider()
            endpoint = os.environ.get("HUB_OTEL_ENDPOINT", "").strip()
            if endpoint:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                provider.add_span_processor(BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=endpoint)))
            otel_trace.set_tracer_provider(provider)
            return otel_trace.get_tracer("uniagent-hub")
        except Exception:  # noqa: BLE001 - Provider 冲突等环境问题降级
            return None

    @property
    def otel_available(self) -> bool:
        return self._otel is not None

    # ---- span 生命周期 ----

    def start(self, name: str, kind: str = "internal", *,
              trace_id: str | None = None, parent_id: str | None = None,
              attributes: dict[str, Any] | None = None) -> SpanHandle:
        parent = _current_span.get()
        trace_id = trace_id or (parent.trace_id if parent else uuid.uuid4().hex[:8])
        parent_id = parent_id or (parent.span_id if parent else None)
        span = Span(trace_id=trace_id, span_id=uuid.uuid4().hex[:8],
                    parent_id=parent_id, name=name, kind=kind,
                    start_ts=time.time(), attributes=dict(attributes or {}))
        with self._lock:
            self._ensure_trace(trace_id)
            self._spans[span.span_id] = span
            self._by_trace[trace_id].append(span.span_id)
        self._otel_start(span)
        self.bus.publish("span.start", span=span.to_dict())
        return SpanHandle(self, span)

    def _ensure_trace(self, trace_id: str) -> None:
        """登记 trace，并在超出上限时淘汰最旧 trace 的全部 span（调用方持锁）。"""
        if trace_id in self._by_trace:
            return
        if len(self._order) == self._order.maxlen:
            evicted = self._order[0]
            for sid in self._by_trace.pop(evicted, []):
                self._spans.pop(sid, None)
        self._by_trace[trace_id] = []
        self._order.append(trace_id)

    def _finish(self, span: Span) -> None:
        self._otel_end(span)
        self.bus.publish("span.end", span=span.to_dict())

    def record_llm_chat(self, *, trace_id: str, parent_id: str | None,
                        model: str, system: str = "openai-compatible",
                        input_tokens: int = 0, output_tokens: int = 0,
                        finish_reasons: list[str] | None = None,
                        latency_ms: float = 0.0,
                        attributes: dict[str, Any] | None = None) -> Span:
        """记录一次 LLM 调用（已完成状态），字段名严格对齐 GenAI SemConv。"""
        span = Span(trace_id=trace_id, span_id=uuid.uuid4().hex[:8],
                    name="llm.chat", kind="llm",
                    start_ts=time.time() - latency_ms / 1000.0,
                    end_ts=time.time(), parent_id=parent_id, status="ok",
                    attributes={
                        GEN_AI_SYSTEM: system,
                        GEN_AI_REQUEST_MODEL: model,
                        GEN_AI_INPUT_TOKENS: input_tokens,
                        GEN_AI_OUTPUT_TOKENS: output_tokens,
                        GEN_AI_FINISH_REASONS: finish_reasons or ["stop"],
                        **(attributes or {}),
                    })
        with self._lock:
            self._ensure_trace(trace_id)
            self._spans[span.span_id] = span
            self._by_trace[trace_id].append(span.span_id)
        self.bus.publish("span.end", span=span.to_dict())
        return span

    # ---- 查询 ----

    def spans_of(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [self._spans[sid].to_dict()
                    for sid in self._by_trace.get(trace_id, [])]

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """最近 trace 列表（每个 trace 含 spans 与根 span 摘要）。"""
        with self._lock:
            trace_ids = list(self._order)[-limit:]
        out = []
        for tid in reversed(trace_ids):
            spans = self.spans_of(tid)
            if not spans:
                continue
            roots = [s for s in spans if not s.get("parent_id")] or spans[:1]
            out.append({
                "trace_id": tid,
                "root": roots[0]["name"],
                "start_ts": min(s["start_ts"] for s in spans),
                "duration_ms": round(max(s["duration_ms"] for s in spans), 2),
                "status": ("error" if any(s["status"] == "error" for s in spans)
                           else "running" if any(s["status"] == "running" for s in spans)
                           else "ok"),
                "span_count": len(spans),
                "spans": spans,
            })
        return out

    def latest(self) -> dict[str, Any] | None:
        items = self.recent(limit=1)
        return items[0] if items else None

    # ---- OTel 双写（尽力而为，失败不影响主链路）----

    def _otel_start(self, span: Span) -> None:
        if self._otel is None:
            return
        try:
            otel_span = self._otel.start_span(
                span.name, attributes={
                    **{k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                       for k, v in span.attributes.items()},
                    "uniagent.trace_id": span.trace_id,
                    "uniagent.span_id": span.span_id,
                })
            self._otel_spans[span.span_id] = otel_span
        except Exception:  # noqa: BLE001
            pass

    def _otel_end(self, span: Span) -> None:
        if self._otel is None:
            return
        try:
            from opentelemetry.trace import Status, StatusCode
            otel_span = self._otel_spans.pop(span.span_id, None)
            if otel_span is not None:
                otel_span.set_status(Status(
                    StatusCode.ERROR if span.status == "error" else StatusCode.OK))
                otel_span.end(end_time=int((span.end_ts or time.time()) * 1e9))
        except Exception:  # noqa: BLE001
            pass


default_tracer = Tracer()


def current_span() -> Span | None:
    return _current_span.get()
