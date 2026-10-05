"""CLI 命令模板解析器（参考 Studio MCP 的 Mustache 风格语法）。

语法：
  {arg}                 必填参数
  {arg # 描述}           带描述的必填参数 → 生成 inputSchema 的 description
  单引号/双引号是"分组"标记（类似 shell 词法），不强制产生元素边界；
  空白是唯一的元素分隔符。占位符与相邻字面量合并为同一 argv 元素：
    例: --file={path} → ["--file=<value>"]
  引号内的空格属于元素内容（不被拆分）。

执行约束（docs/unispec.md §7）：禁止 shell=True 与字符串拼接，一律 argv 数组。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(\s*#\s*([^}]*))?\}")


@dataclass
class ArgSpec:
    name: str
    description: str = ""
    required: bool = True


@dataclass(frozen=True)
class Segment:
    """argv 单个元素中的一段：字面量或参数占位符。"""
    literal: str = ""
    placeholder: str | None = None


def parse_template(command: str) -> tuple[list[list[Segment]], list[ArgSpec]]:
    """解析命令模板 → (argv 元素列表, 参数定义)。"""
    elements: list[list[Segment]] = []
    arg_specs: dict[str, ArgSpec] = {}

    i, n = 0, len(command)
    current: list[Segment] = []
    in_quote: str | None = None  # "'" or '"'

    def flush() -> None:
        nonlocal current
        if current:
            elements.append(current)
            current = []

    def push_literal(ch: str) -> None:
        if current and current[-1].placeholder is None:
            current[-1] = Segment(literal=current[-1].literal + ch)
        else:
            current.append(Segment(literal=ch))

    def push_placeholder(name: str, desc: str) -> None:
        spec = arg_specs.setdefault(name, ArgSpec(name=name))
        if desc:
            spec.description = desc
        current.append(Segment(placeholder=name))

    while i < n:
        ch = command[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
                i += 1
                continue
            m = _PLACEHOLDER_RE.match(command, i)
            if m:
                push_placeholder(m.group(1), (m.group(3) or "").strip())
                i = m.end()
                continue
            push_literal(ch)
            i += 1
        elif ch in ("'", '"'):
            in_quote = ch
            i += 1
        elif ch.isspace():
            flush()
            while i < n and command[i].isspace():
                i += 1
        else:
            m = _PLACEHOLDER_RE.match(command, i)
            if m:
                push_placeholder(m.group(1), (m.group(3) or "").strip())
                i = m.end()
                continue
            push_literal(ch)
            i += 1
    flush()
    return elements, list(arg_specs.values())


def generate_schema(command: str) -> dict[str, Any]:
    """从命令模板自动生成 MCP inputSchema。"""
    _, args = parse_template(command)
    properties = {
        a.name: {
            "type": "string",
            **({"description": a.description} if a.description else {}),
        }
        for a in args
    }
    return {
        "type": "object",
        "properties": properties,
        "required": [a.name for a in args if a.required],
    }


def build_argv(elements: list[list[Segment]], values: dict[str, Any]) -> list[str]:
    """将模板元素与已校验的参数值拼装为 argv 数组（subprocess argv 模式）。"""
    argv: list[str] = []
    for elem in elements:
        parts = [str(values[s.placeholder]) if s.placeholder is not None else s.literal
                 for s in elem]
        argv.append("".join(parts))
    return argv
