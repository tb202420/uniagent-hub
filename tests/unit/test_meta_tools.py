"""Meta-Tools 渐进式工具发现测试（改进方案 §3）。"""

import subprocess
import tempfile
from pathlib import Path

from adapters.cli_adapter.adapter import CLIAdapter
from core.gateway.meta_tools import MetaTools
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
      repo_path: "^[a-zA-Z0-9_/.~: -]+$"

  - id: "cli.file.search"
    name: "文件搜索"
    command: "find {directory # 搜索目录} -name '{pattern # 文件名模式}' -type f"
    tool_name: "file_search"
    readOnly: true
    timeout: 10s
    allowed_commands: ["find"]
    param_patterns:
      directory: "^[a-zA-Z0-9_/.~: -]+$"
      pattern: "^[a-zA-Z0-9_./*~ -]+$"
"""

_VIRTUAL = {"name": "run_workflow", "title": "运行工作流", "description": "工作流编排",
            "inputSchema": {"type": "object", "properties": {}}}


def _gw(tmp: str, meta: bool = True) -> MCPGateway:
    cfg = Path(tmp) / "cli_tools.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    reg = ToolRegistry(SQLiteStore(Path(tmp) / "t.db"))
    CLIAdapter(reg, config_path=cfg).discover()
    reg.register_tool("run_workflow", _VIRTUAL)
    audit = AuditLogger(AuditStore(max_memory=200))
    gw = MCPGateway(reg, audit)
    if meta:
        gw.meta_tools = MetaTools(gw)
    return gw


def test_meta_mode_exposes_only_four_tools():
    gw = _gw(tempfile.mkdtemp())
    names = [t["name"] for t in gw.list_tools()["tools"]]
    assert names == ["discover_tools", "get_tool_schema", "execute_tool",
                     "refresh_registry"]


def test_default_mode_keeps_full_list():
    gw = _gw(tempfile.mkdtemp(), meta=False)
    names = {t["name"] for t in gw.list_tools()["tools"]}
    assert {"git_status", "file_search", "run_workflow"} <= names


def test_discover_domains_summary():
    gw = _gw(tempfile.mkdtemp())
    res = gw.call({"name": "discover_tools", "arguments": {}, "caller": "t"})
    assert res["isError"] is False
    import json
    data = json.loads(res["content"][0]["text"])
    domains = {d["domain"]: d for d in data["domains"]}
    assert domains["cli"]["count"] == 2
    assert domains["workflow"]["count"] == 1
    assert data["total"] == 3


def test_discover_by_domain_and_query():
    gw = _gw(tempfile.mkdtemp())
    import json
    res = gw.call({"name": "discover_tools",
                   "arguments": {"domain": "cli"}, "caller": "t"})
    data = json.loads(res["content"][0]["text"])
    assert data["count"] == 2
    res = gw.call({"name": "discover_tools",
                   "arguments": {"query": "git"}, "caller": "t"})
    data = json.loads(res["content"][0]["text"])
    assert [t["name"] for t in data["tools"]] == ["git_status"]


def test_get_schema_fuzzy():
    gw = _gw(tempfile.mkdtemp())
    import json
    res = gw.call({"name": "get_tool_schema",
                   "arguments": {"name": "gitstat"}, "caller": "t"})
    assert res["isError"] is False
    schema = json.loads(res["content"][0]["text"])
    assert schema["name"] == "git_status"
    assert "repo_path" in schema["inputSchema"]["properties"]


def test_get_schema_not_found():
    gw = _gw(tempfile.mkdtemp())
    res = gw.call({"name": "get_tool_schema",
                   "arguments": {"name": "zzzz"}, "caller": "t"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1001


def test_get_schema_ambiguous():
    gw = _gw(tempfile.mkdtemp())
    gw.registry.register_tool("git_status_extra", {
        "name": "git_status_extra", "description": "x",
        "inputSchema": {"type": "object", "properties": {}}})
    import json
    res = gw.call({"name": "get_tool_schema",
                   "arguments": {"name": "git"}, "caller": "t"})
    assert res["isError"] is False
    data = json.loads(res["content"][0]["text"])
    assert data["ambiguous"] is True
    assert set(data["candidates"]) == {"git_status", "git_status_extra"}


def test_execute_tool_routes_through_guard():
    tmp = tempfile.mkdtemp()
    repo = Path(tmp) / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "x.txt").write_text("hello", encoding="utf-8")
    gw = _gw(tmp)
    res = gw.call({"name": "execute_tool",
                   "arguments": {"tool": "git_status",
                                 "arguments": {"repo_path": str(repo)}},
                   "caller": "t"})
    assert res["isError"] is False
    assert "x.txt" in res["content"][0]["text"]


def test_execute_tool_injection_blocked():
    gw = _gw(tempfile.mkdtemp())
    res = gw.call({"name": "execute_tool",
                   "arguments": {"tool": "file_search",
                                 "arguments": {"directory": ".", "pattern": "x; rm -rf /"}},
                   "caller": "t"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1007


def test_execute_tool_unknown():
    gw = _gw(tempfile.mkdtemp())
    res = gw.call({"name": "execute_tool",
                   "arguments": {"tool": "nope"}, "caller": "t"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1001


def test_execute_tool_recursion_blocked():
    gw = _gw(tempfile.mkdtemp())
    res = gw.call({"name": "execute_tool",
                   "arguments": {"tool": "execute_tool", "arguments": {}},
                   "caller": "t"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1002


def test_meta_args_validated():
    gw = _gw(tempfile.mkdtemp())
    res = gw.call({"name": "discover_tools",
                   "arguments": {"domain": "nope"}, "caller": "t"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1002


def test_refresh_registry_diff():
    gw = _gw(tempfile.mkdtemp())
    import json
    res = gw.call({"name": "refresh_registry", "arguments": {}, "caller": "t"})
    first = json.loads(res["content"][0]["text"])
    assert set(first["added"]) == {"git_status", "file_search", "run_workflow"}
    gw.registry.register_tool("late_tool", {
        "name": "late_tool", "description": "x",
        "inputSchema": {"type": "object", "properties": {}}})
    res = gw.call({"name": "refresh_registry", "arguments": {}, "caller": "t"})
    second = json.loads(res["content"][0]["text"])
    assert second["added"] == ["late_tool"]
    assert second["removed"] == []


def test_meta_calls_audited():
    gw = _gw(tempfile.mkdtemp())
    gw.call({"name": "discover_tools", "arguments": {}, "caller": "t"})
    gw.call({"name": "execute_tool",
             "arguments": {"tool": "git_status", "arguments": {"repo_path": "."}},
             "caller": "t"})
    tools = {r["tool"] for r in gw.audit.store.query(limit=20)}
    assert {"discover_tools", "execute_tool"} <= tools


def test_meta_audit_carries_schema_hash():
    """A2 修复：元层审计记录应携带其自身工具定义的内容哈希（非空）。"""
    from core.guard.attestation import schema_hash
    gw = _gw(tempfile.mkdtemp())
    gw.call({"name": "execute_tool",
             "arguments": {"tool": "git_status",
                           "arguments": {"repo_path": "."}},
             "caller": "t"})
    rows = {r["tool"]: r for r in gw.audit.store.query(limit=20)}
    meta_hash = rows["execute_tool"].get("schema_hash", "")
    assert meta_hash, "元层审计记录 schema_hash 不应为空"
    meta_def = next(d for d in gw.meta_tools.definitions()
                    if d["name"] == "execute_tool")
    assert meta_hash == schema_hash(meta_def)