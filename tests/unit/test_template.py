"""CLI 模板解析器单元测试（含注入防护相关）。"""

from adapters.cli_adapter.template import parse_template, generate_schema, build_argv


def test_parse_simple():
    elements, args = parse_template("git status --short")
    assert [e[0].literal for e in elements if e and e[0].literal] == ["git", "status", "--short"]
    assert args == []


def test_parse_placeholders():
    elements, args = parse_template("find {directory} -name '{pattern}' -type f")
    assert [a.name for a in args] == ["directory", "pattern"]
    # '{pattern}' 引号剥离后仍是一个 argv 元素
    assert len(elements) == 6


def test_schema_generation_with_description():
    schema = generate_schema("find {directory # 搜索目录} -name '{pattern # 文件名模式}'")
    assert schema["required"] == ["directory", "pattern"]
    assert schema["properties"]["directory"]["description"] == "搜索目录"
    assert schema["properties"]["pattern"]["description"] == "文件名模式"
    assert schema["type"] == "object"


def test_quoted_literal_prefix_merge():
    # '--name={x}' 这类：字面量前缀与占位符合并为同一 argv 元素
    elements, args = parse_template("cmd '--file={path}' -x")
    joined = []
    for e in elements:
        joined.append("".join(s.literal or "{" + s.placeholder + "}" for s in e))
    assert joined == ["cmd", "--file={path}", "-x"]
    assert [a.name for a in args] == ["path"]


def test_build_argv():
    elements, _ = parse_template("find {directory} -name '{pattern}' -type f")
    argv = build_argv(elements, {"directory": "/tmp", "pattern": "*.py"})
    assert argv == ["find", "/tmp", "-name", "*.py", "-type", "f"]


def test_build_argv_multi_part_token():
    elements, _ = parse_template("cmd --file={path}")
    argv = build_argv(elements, {"path": "a b"})
    assert argv == ["cmd", "--file=a b"]
