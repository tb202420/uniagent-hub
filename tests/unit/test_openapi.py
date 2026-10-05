"""OpenAPI 解析器单元测试。"""

import pytest

from adapters.rest_adapter.openapi import load_spec, resolve_refs, simplify_schema

SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/v1/forecast": {
            "get": {
                "operationId": "get_weather",
                "parameters": [
                    {"name": "latitude", "in": "query", "required": True,
                     "schema": {"$ref": "#/components/schemas/Lat"}},
                    {"name": "current_weather", "in": "query",
                     "schema": {"type": "boolean", "default": True}},
                ],
            }
        }
    },
    "components": {
        "schemas": {
            "Lat": {"type": "number", "description": "纬度"},
        }
    },
}


def test_resolve_internal_ref():
    resolved = resolve_refs(SPEC, SPEC)
    param = resolved["paths"]["/v1/forecast"]["get"]["parameters"][0]
    assert param["schema"]["type"] == "number"
    assert param["schema"]["description"] == "纬度"
    assert "$ref" not in param["schema"]


def test_external_ref_downgraded():
    spec = {"a": {"$ref": "other.yaml#/x"}}
    out = resolve_refs(spec, spec)
    assert out["a"]["type"] == "object"
    assert "外部" in out["a"]["description"]


def test_circular_ref_detected():
    spec = {"a": {"$ref": "#/a"}}
    with pytest.raises(ValueError, match="循环"):
        resolve_refs(spec, spec)


def test_simplify_oneof_downgrade():
    out = simplify_schema({"oneOf": [{"type": "string"}, {"type": "null"}]})
    assert out["type"] == "object"
    assert "降级" in out["description"]


def test_simplify_basic():
    assert simplify_schema({"type": "integer", "enum": [1, 2]})["type"] == "integer"
    assert simplify_schema({"type": "array",
                            "items": {"type": "string"}})["items"]["type"] == "string"


def test_load_spec_from_file():
    from pathlib import Path
    import tempfile, yaml
    p = Path(tempfile.mkdtemp()) / "s.yaml"
    p.write_text(yaml.safe_dump(SPEC), encoding="utf-8")
    loaded = load_spec(p)
    assert loaded["openapi"] == "3.0.0"


def test_load_spec_missing_file():
    with pytest.raises(FileNotFoundError):
        load_spec("no_such_file.yaml")
