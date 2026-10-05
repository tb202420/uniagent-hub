"""安全表达式解析器单元测试（零 eval）。"""

import pytest

from core.workflow.expr import ExprError, safe_eval


def test_arithmetic():
    assert safe_eval("25.5 - 2") == 23.5
    assert safe_eval("10 + 5 * 2") == 20
    assert safe_eval("(10 + 5) * 2") == 30
    assert safe_eval("8 / 2") == 4.0


def test_comparison():
    assert safe_eval("29.5 > 28") is True
    assert safe_eval("28 >= 28") is True
    assert safe_eval("27 == 28") is False
    assert safe_eval("27 != 28") is True


def test_logic():
    assert safe_eval("1 < 2 and 3 > 2") is True
    assert safe_eval("1 > 2 or 3 > 2") is True
    assert safe_eval("not 1 > 2") is True


def test_strings():
    assert safe_eval("'on' == 'on'") is True
    assert safe_eval("'on' == 'off'") is False
    assert safe_eval("'on'") == "on"


@pytest.mark.parametrize("bad", [
    "__import__('os').system('x')",
    "open('/etc/passwd')",
    "globals()",
    "1; import os",
    "lambda: 1",
    "[1,2,3]",
    "a = 1",
    "",
])
def test_injection_rejected(bad):
    with pytest.raises(ExprError):
        safe_eval(bad)


def test_div_by_zero():
    with pytest.raises(ExprError, match="除零"):
        safe_eval("1 / 0")


def test_string_only_equality():
    with pytest.raises(ExprError):
        safe_eval("'a' > 'b'")
