"""安全表达式求值器（工作流专用，零 eval）。

语法子集：
- 数字、字符串字面量（单引号）
- 算术: + - * / 与括号
- 比较: == != < > <= >=
- 逻辑: and / or / not
引用（{{...}}）由调用方先替换为 Python repr（数字/字符串），
本模块只解析"数字/字符串/运算符/括号"，无任何 Python eval。

设计动机（答辩要点）：工作流条件表达式绝不能用 eval，
否则 Agent 传入的表达式就是命令注入变体。
"""

from __future__ import annotations

import re
from typing import Any

_NUM_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


class ExprError(ValueError):
    pass


# ---- 词法 ----

_TOKEN_RE = re.compile(
    r"""
    (?P<num>[+-]?\d+(?:\.\d+)?)
  | (?P<str>'(?:[^'\\]|\\.)*')
  | (?P<op>==|!=|<=|>=|and|or|not|\+|-|\*|/|\(|\)|[<>])
  | (?P<ws>\s+)
  """,
    re.VERBOSE,
)


def _tokenize(s: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if m is None:
            raise ExprError(f"无法解析的字符: {s[pos:pos+12]!r}（位置 {pos}）")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        if kind == "num":
            tokens.append(("num", float(m.group())))
        elif kind == "str":
            tokens.append(("str", m.group()[1:-1].replace("\\'", "'")))
        else:
            tokens.append(("op", m.group()))
    return tokens


# ---- 递归下降解析：expr := or ----

class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, Any] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> tuple[str, Any]:
        t = self._peek()
        if t is None:
            raise ExprError("表达式意外结束")
        self._pos += 1
        return t

    def parse(self) -> Any:
        if not self._tokens:
            raise ExprError("空表达式")
        value = self._or()
        if self._peek() is not None:
            raise ExprError(f"多余的 token: {self._peek()!r}")
        return value

    def _or(self) -> Any:
        left = self._and()
        while self._peek() and self._peek()[1] == "or":
            self._next()
            right = self._and()
            left = bool(left) or bool(right)
        return left

    def _and(self) -> Any:
        left = self._not()
        while self._peek() and self._peek()[1] == "and":
            self._next()
            right = self._not()
            left = bool(left) and bool(right)
        return left

    def _not(self) -> Any:
        if self._peek() and self._peek()[1] == "not":
            self._next()
            return not bool(self._not())
        return self._comparison()

    def _comparison(self) -> Any:
        left = self._arith()
        op = self._peek()
        if op and op[1] in ("==", "!=", "<", ">", "<=", ">="):
            self._next()
            right = self._arith()
            a, b = left, right
            if isinstance(a, str) or isinstance(b, str):
                if op[1] == "==":
                    return a == b
                if op[1] == "!=":
                    return a != b
                raise ExprError("字符串仅支持 == / !=")
            return {
                "==": lambda: a == b, "!=": lambda: a != b,
                "<": lambda: a < b, ">": lambda: a > b,
                "<=": lambda: a <= b, ">=": lambda: a >= b,
            }[op[1]]()
        return left

    def _arith(self) -> Any:
        left = self._term()
        while self._peek() and self._peek()[1] in ("+", "-"):
            op = self._next()[1]
            right = self._term()
            left = left + right if op == "+" else left - right
        return left

    def _term(self) -> Any:
        left = self._factor()
        while self._peek() and self._peek()[1] in ("*", "/"):
            op = self._next()[1]
            right = self._factor()
            if op == "/" and right == 0:
                raise ExprError("除零")
            left = left * right if op == "*" else left / right
        return left

    def _factor(self) -> Any:
        t = self._peek()
        if t is None:
            raise ExprError("表达式意外结束")
        if t[1] == "(":
            self._next()
            v = self._or()
            close = self._next()
            if close[1] != ")":
                raise ExprError("缺少右括号")
            return v
        kind, value = self._next()
        if kind in ("num", "str"):
            return value
        raise ExprError(f"意外的 token: {value!r}")


def safe_eval(expr: str) -> Any:
    """安全求值（数字/字符串/比较/逻辑/算术），失败抛 ExprError。"""
    return _Parser(_tokenize(expr)).parse()


def is_numeric(s: str) -> bool:
    return bool(_NUM_RE.match(s.strip()))
