"""可观测层（v3.0）：OTel GenAI SemConv 字段契约 + 本地 span 存储 + OTel 双写。"""

from core.observability.tracer import (  # noqa: F401
    GEN_AI_FINISH_REASONS, GEN_AI_INPUT_TOKENS, GEN_AI_OUTPUT_TOKENS,
    GEN_AI_REQUEST_MODEL, GEN_AI_SYSTEM, Span, Tracer, current_span,
    default_tracer,
)
