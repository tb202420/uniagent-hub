"""OpenAPI 最小解析器（阶段 2，无外部依赖）。

- 支持 OpenAPI 3.0 / 3.1 子集：本地文件或 URL 加载（YAML / JSON）
- $ref 解析：#/components/... 内部引用（带循环检测与深度限制；外部引用降级）
- 复杂 Schema（oneOf/anyOf 等）降级为 type: object 并在 description 说明
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

_REF_RE = re.compile(r"^#/(.*)$")
_MAX_DEPTH = 50


def load_spec(source: str | Path) -> dict[str, Any]:
    """从本地文件或 URL 加载 OpenAPI Spec（自动识别 YAML/JSON）。"""
    if isinstance(source, Path):
        src = source
    elif isinstance(source, str) and not source.startswith(("http://", "https://")):
        src = Path(source)
    else:
        src = None
    if src is not None:
        if not src.exists():
            raise FileNotFoundError(f"OpenAPI Spec 文件不存在: {src}")
        text = src.read_text(encoding="utf-8")
    else:
        resp = httpx.get(str(source), timeout=15)
        resp.raise_for_status()
        text = resp.text
    try:
        return yaml.safe_load(text)
    except Exception:
        return json.loads(text)


def resolve_refs(node: Any, root: dict[str, Any], _seen: set[str] | None = None,
                 _depth: int = 0) -> Any:
    """递归解析内部 $ref（#/components/...），带循环检测与深度限制。"""
    if _depth > _MAX_DEPTH:
        raise ValueError("OpenAPI $ref 嵌套过深")
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                # 外部引用不支持 → 降级为通用对象
                return {"type": "object", "description": f"[外部 $ref 未解析: {ref}]"}
            key = ref
            if key in (_seen or set()):
                raise ValueError(f"$ref 循环引用: {key}")
            target = root
            for part in ref[2:].split("/"):
                if not isinstance(target, dict) or part not in target:
                    return {"type": "object", "description": f"[无法解析 $ref: {ref}]"}
                target = target[part]
            merged = {**node, **resolve_refs(target, root,
                                             (_seen or set()) | {key}, _depth + 1)}
            merged.pop("$ref", None)
            return merged
        return {k: resolve_refs(v, root, _seen, _depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(v, root, _seen, _depth + 1) for v in node]
    return node


def simplify_schema(schema: Any) -> dict[str, Any]:
    """OpenAPI 参数 Schema → UniSpec inputSchema 属性（复杂类型降级）。"""
    if not isinstance(schema, dict):
        return {"type": "string"}
    if any(k in schema for k in ("oneOf", "anyOf", "allOf", "not")):
        return {
            "type": "object",
            "description": (schema.get("description", "") +
                            " [复合 Schema 已降级为 object]").strip(),
        }
    stype = schema.get("type", "string")
    if stype not in ("string", "number", "integer", "boolean", "array", "object"):
        stype = "object"
    out: dict[str, Any] = {"type": stype}
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        out["enum"] = schema["enum"]
    if stype in ("string",) and "format" in schema:
        out["format"] = schema["format"]
    if stype == "array" and isinstance(schema.get("items"), dict):
        out["items"] = simplify_schema(schema["items"])
    return out
