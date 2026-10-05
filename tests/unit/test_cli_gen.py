"""CLI 反向生成单元测试。"""

from pathlib import Path

from core.cli_gen.generator import CLIGenerator

TOOL = {
    "name": "git_status",
    "description": "查看指定仓库的 Git 工作区状态（只读）",
    "inputSchema": {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Git 仓库绝对路径"},
            "short": {"type": "boolean", "description": "简短输出", "default": True},
        },
        "required": ["repo_path"],
    },
}


def test_script_text_contains_argparse(tmp_path: Path):
    gen = CLIGenerator(hub_url="http://x:8000", out_dir=tmp_path)
    text = gen.script_text(TOOL)
    assert "git_status" in text
    assert "repo_path" in text
    assert "required=True" in text
    assert "default=True" in text
    # 关键：禁止 eval/exec/shell 拼接
    assert "eval(" not in text and "exec(" not in text


def test_generate_writes_file(tmp_path: Path):
    gen = CLIGenerator(hub_url="http://x:8000", out_dir=tmp_path)
    path = gen.generate(TOOL)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")


def test_generate_all_excludes_run_workflow(tmp_path: Path):
    gen = CLIGenerator(out_dir=tmp_path)
    paths = gen.generate_all([TOOL, {"name": "run_workflow", "description": "x",
                                     "inputSchema": {}}])
    assert len(paths) == 1
    assert (tmp_path / "README.md").exists()
