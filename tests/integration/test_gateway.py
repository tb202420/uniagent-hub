"""Gateway 集成测试：CLI 适配器 → 参数校验 → 注入拦截 端到端。"""

import os
import subprocess
import tempfile
from pathlib import Path

from adapters.cli_adapter.adapter import CLIAdapter
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry

CONFIG = r"""
cli_tools:
  - id: "cli.git.status"
    name: "Git 状态查询"
    command: "git -C {repo_path # Git 仓库绝对路径} status --short"
    tool_name: "git_status"
    readOnly: true
    timeout: 10s
    allowed_commands: ["git"]
    param_patterns:
      repo_path: "^[a-zA-Z0-9_/.~: -]+$"

  - id: "cli.file.search"
    name: "文件搜索"
    command: "find {directory # 搜索目录} -name '{pattern # 文件名模式，支持 * 通配}' -type f"
    tool_name: "file_search"
    readOnly: true
    timeout: 10s
    allowed_commands: ["find"]
    param_patterns:
      directory: "^[a-zA-Z0-9_/.~: -]+$"
      pattern: "^[a-zA-Z0-9_./*~ -]+$"
"""


def _make_gateway(tmp: str) -> MCPGateway:
    cfg = Path(tmp) / "cli_tools.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    reg = ToolRegistry()
    CLIAdapter(reg, config_path=cfg).discover()
    audit = AuditLogger(AuditStore(max_memory=100))
    return MCPGateway(reg, audit)


def test_tools_list():
    gw = _make_gateway(tempfile.mkdtemp())
    result = gw.list_tools()
    names = {t["name"] for t in result["tools"]}
    assert {"git_status", "file_search"} <= names
    by_name = {t["name"]: t for t in result["tools"]}
    assert by_name["file_search"]["inputSchema"]["required"] == ["directory", "pattern"]


def test_call_git_status_ok():
    gw = _make_gateway(tempfile.mkdtemp())
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", tmp], check=True)
    Path(tmp, "x.txt").write_text("hello", encoding="utf-8")
    res = gw.call({"name": "git_status",
                    "arguments": {"repo_path": tmp}})
    assert res["isError"] is False
    assert "x.txt" in res["content"][0]["text"]


def test_injection_blocked():
    gw = _make_gateway(tempfile.mkdtemp())
    res = gw.call({"name": "file_search",
                    "arguments": {"directory": "/tmp", "pattern": "x; rm -rf /"}})
    assert res["isError"] is True
    assert "注入防护" in res["content"][0]["text"]


def test_unknown_tool():
    gw = _make_gateway(tempfile.mkdtemp())
    res = gw.call({"name": "nope", "arguments": {}})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1001


def test_audit_written():
    gw = _make_gateway(tempfile.mkdtemp())
    gw.call({"name": "file_search", "arguments": {"directory": "/tmp", "pattern": "*.py"}})
    rows = gw.audit.store.query()
    assert len(rows) == 1
    assert rows[0]["tool"] == "file_search"
    assert rows[0]["guard_result"] in ("passed", "blocked")
