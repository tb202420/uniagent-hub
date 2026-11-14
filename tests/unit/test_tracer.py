"""追踪记录器单元测试（v3.0 批次，GenAI SemConv 字段契约）。"""

from core.gateway.event_bus import EventBus
from core.observability.tracer import (
    GEN_AI_FINISH_REASONS, GEN_AI_INPUT_TOKENS, GEN_AI_OUTPUT_TOKENS,
    GEN_AI_REQUEST_MODEL, GEN_AI_SYSTEM, Tracer,
)


def test_span_start_end_and_grouping():
    tracer = Tracer(bus=EventBus())
    with tracer.start("agent.run", "agent", trace_id="t1") as span:
        assert span.trace_id == "t1"
        with tracer.start("tool.control_pump", "tool") as child:
            assert child.parent_id == span.span_id
    trace = tracer.recent()[0]
    assert trace["trace_id"] == "t1"
    assert trace["root"] == "agent.run"
    assert trace["span_count"] == 2
    assert trace["status"] == "ok"


def test_span_publishes_events():
    bus = EventBus()
    tracer = Tracer(bus=bus)
    with tracer.start("tool.x", "tool", trace_id="t2"):
        pass
    kinds = [e["kind"] for e in bus.since(0)]
    assert kinds == ["span.start", "span.end"]


def test_error_status_on_exception():
    tracer = Tracer(bus=EventBus())
    try:
        with tracer.start("tool.bad", "tool", trace_id="t3"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    spans = tracer.spans_of("t3")
    assert spans[0]["status"] == "error"


def test_llm_chat_semconv_attributes():
    tracer = Tracer(bus=EventBus())
    span = tracer.record_llm_chat(
        trace_id="t4", parent_id=None, model="deepseek-chat",
        input_tokens=120, output_tokens=48,
        finish_reasons=["stop"], latency_ms=850.0)
    attrs = span.attributes
    assert attrs[GEN_AI_SYSTEM] == "openai-compatible"
    assert attrs[GEN_AI_REQUEST_MODEL] == "deepseek-chat"
    assert attrs[GEN_AI_INPUT_TOKENS] == 120
    assert attrs[GEN_AI_OUTPUT_TOKENS] == 48
    assert attrs[GEN_AI_FINISH_REASONS] == ["stop"]
    assert tracer.spans_of("t4")[0]["duration_ms"] > 0


def test_trace_pruning_keeps_recent():
    tracer = Tracer(bus=EventBus(), max_traces=2)
    for i in range(3):
        with tracer.start("tool.x", "tool", trace_id=f"p{i}"):
            pass
    assert [t["trace_id"] for t in tracer.recent()] == ["p2", "p1"]
    assert tracer.spans_of("p0") == []
