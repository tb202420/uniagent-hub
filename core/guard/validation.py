"""Guard 参数校验（MVP 版，阶段 2 换 Zod/jsonschema 完整实现）。

实现 JSON Schema 子集校验 + 命令注入白名单：
- 校验 inputSchema 的 type / required / enum / pattern / properties
- 对字符串参数应用 paramPatterns（默认拒绝 shell 元字符）
"""

from __future__ import annotations

import re
from typing import Any

# 默认注入防护白名单：仅允许安全字符集（含 Windows 盘符冒号）。
# 显式排除 ; & | ` $ ( ) < > " ' \ 换行 等 shell 元字符。
DEFAULT_ARG_PATTERN = r"^[a-zA-Z0-9_/.:\- *]+$"
_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _compile(p: str) -> re.Pattern:
    if p not in _PATTERN_CACHE:
        _PATTERN_CACHE[p] = re.compile(p)
    return _PATTERN_CACHE[p]


def _is_type(value: Any, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t in ("object", "array"):
        return isinstance(value, dict if t == "object" else list)
    if t == "null":
        return value is None
    return True  # 未知类型放行（交给上游语义处理）


def validate_args(input_schema: dict[str, Any], args: dict[str, Any],
                  param_patterns: dict[str, str] | None = None) -> list[str]:
    """返回错误列表；空列表表示通过。"""
    errors: list[str] = []
    props: dict[str, Any] = input_schema.get("properties", {})
    required: list[str] = input_schema.get("required", [])

    # 1. 未知参数（MVP：拒绝，防参数注入）
    for key in args:
        if key not in props:
            errors.append(f"未知参数: {key}")
    # 2. 必填检查
    for key in required:
        if key not in args or args[key] is None:
            errors.append(f"缺少必填参数: {key}")
    # 3. 类型 / enum / pattern / 范围 / 白名单
    for key, schema in props.items():
        if key not in args or args[key] is None:
            continue
        value = args[key]
        if "type" in schema and not _is_type(value, schema["type"]):
            errors.append(f"参数 {key} 类型错误: 期望 {schema['type']}，实际 {type(value).__name__}")
            continue
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"参数 {key} 必须在 {schema['enum']} 中，实际 {value!r}")
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"参数 {key} 低于最小值 {schema['minimum']}: {value!r}")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"参数 {key} 超过最大值 {schema['maximum']}: {value!r}")
        if isinstance(value, str):
            # 空字符串无注入风险，放行（可选参数缺省场景）
            if value == "":
                continue
            pat = schema.get("pattern") or (param_patterns or {}).get(key) or DEFAULT_ARG_PATTERN
            if not _compile(pat).match(value):
                errors.append(f"参数 {key} 含非法字符（注入防护拦截）: {value!r}")
    return errors
