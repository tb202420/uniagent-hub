"""FastMCP 4 兼容前端集成测试（改进方案 §2+§3，in-memory Client）。

协议前端交给 FastMCP，执行仍经自研网关（Guard 管道 + 审计 +
execute_tool 递归防护），本测试验证端到端语义一致。
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")

from adapters.cli_adapter.adapter import CLIAdapter
from core.gateway.fastmcp_server import build_fastmcp_server
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

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
      repo_path: "^[a-zA-Z0-9_/.: -]+$"

  - id: "cli.file.search"
    name: "文件搜索"
    command: "find {directory # 搜索目录} -name '{pattern # 文件名模式}' -type f"
    tool_name: "file_search"
    readOnly: true
    timeout: 10s
    allowed_commands: ["find"]
    param_patterns:
      directory: "^[a-zA-Z0-9_/.: -]+$"
      pattern: "^[a-zA-Z0-9_./* -]+$"
"""


def _gw(tmp: str) -> MCPGateway:
    cfg = Path(tmp) / "cli_tools.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    reg = ToolRegistry(SQLiteStore(Path(tmp) / "t.db"))
    CLIAdapter(reg, config_path=cfg).discover()
    audit = AuditLogger(AuditStore(max_memory=200))
    return MCPGateway(reg, audit)


def test_front_exposes_meta_tools_and_enables_gateway_meta():
    gw = _gw(tempfile.mkdtemp())
    server = build_fastmcp_server(gw)

    async def run():
        from fastmcp import Client
        async with Client(server) as client:
            return [t.name for t in await client.list_tools()]

    names = asyncio.run(run())
    assert set(names) == {"discover_tools", "get_tool_schema",
                          "execute_tool", "refresh_registry"}
    assert gw.meta_tools is not None      # 前端构建时自动启用网关 meta 分支


def test_execute_through_guard_and_audit():
    tmp = tempfile.mkdtemp()
    repo = Path(tmp) / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "x.txt").write_text("hello", encoding="utf-8")
    gw = _gw(tmp)
    server = build_fastmcp_server(gw)

    async def run():
        from fastmcp import Client
        async with Client(server) as client:
            return await client.call_tool(
                "execute_tool",
                {"tool": "git_status", "arguments": {"repo_path": str(repo)}})

    res = asyncio.run(run())
    assert "x.txt" in str(res)
    tools = {r["tool"] for r in gw.audit.store.query(limit=20)}
    assert {"git_status", "execute_tool"} <= tools     # 内外两层均落审计


def test_discover_via_front():
    gw = _gw(tempfile.mkdtemp())
    server = build_fastmcp_server(gw)

    async def run():
        from fastmcp import Client
        async with Client(server) as client:
            return await client.call_tool("discover_tools", {"domain": "cli"})

    res = asyncio.run(run())
    assert "git_status" in str(res)


def test_injection_raises_tool_error():
    gw = _gw(tempfile.mkdtemp())
    server = build_fastmcp_server(gw)

    async def run():
        from fastmcp import Client
        async with Client(server) as client:
            return await client.call_tool(
                "execute_tool",
                {"tool": "file_search",
                 "arguments": {"directory": ".", "pattern": "x; rm -rf /"}})

    with pytest.raises(Exception) as exc:      # FastMCP 侧表现为工具错误
        asyncio.run(run())
    assert "1007" in str(exc.value)