"""Guard 参数校验（注入防护）单元测试。"""

import re

import pytest

from core.guard.validation import validate_args, DEFAULT_ARG_PATTERN

SCHEMA = {
    "type": "object",
    "properties": {
        "directory": {"type": "string", "pattern": "^[a-zA-Z0-9_/.:\\\\ -]+$"},
        "pattern": {"type": "string"},
        "limit": {"type": "integer"},
        "mode": {"type": "string", "enum": ["fast", "full"]},
    },
    "required": ["directory"],
}


def test_valid_args_pass():
    assert validate_args(SCHEMA, {"directory": "C:/tmp", "pattern": "*.py", "limit": 3}) == []


def test_missing_required():
    errs = validate_args(SCHEMA, {"pattern": "x"})
    assert any("缺少必填参数" in e for e in errs)


def test_type_mismatch():
    errs = validate_args(SCHEMA, {"directory": "d", "limit": "abc"})
    assert any("类型错误" in e for e in errs)


def test_enum():
    errs = validate_args(SCHEMA, {"directory": "d", "mode": "turbo"})
    assert any("必须在" in e for e in errs)


@pytest.mark.parametrize("evil", [
    "x; rm -rf /",
    "x && cat /etc/passwd",
    "x|sh",
    "x$(id)",
    "x`id`",
    "x> /dev/null",
    "x'quote'",
    'x"quote"',
    "x\\touch",
    "x\nrm",
])
def test_injection_patterns_blocked(evil):
    errs = validate_args({"type": "object", "properties": {"p": {"type": "string"}}},
                         {"p": evil})
    assert any("注入防护" in e for e in errs), f"应拦截: {evil!r}"


def test_glob_allowed():
    assert validate_args({"type": "object", "properties": {"p": {"type": "string"}}},
                         {"p": "*.py"}) == []


def test_default_pattern_blocks_shell_meta():
    assert re.fullmatch(DEFAULT_ARG_PATTERN, "a;b") is None
