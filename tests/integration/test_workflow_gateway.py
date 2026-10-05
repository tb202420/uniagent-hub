"""Gateway × WorkflowEngine 集成测试：run_workflow 走 Guard 管道。"""

import tempfile
from pathlib import Path

from adapters.cli_adapter.adapter import CLIAdapter
from adapters.script_adapter.adapter import ScriptAdapter
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore
from core.workflow.engine import WorkflowEngine

HERE = Path(__file__).resolve().parents[2]

WORKFLOWS = {
    "demo_flow": {
        "steps": [
            {"id": "s1", "tool": "file_summary",
             "args": {"directory": ".", "ext": ""}},
            {"id": "s2", "tool": "file_summary",
             "args": {"directory": ".", "ext": "py"},
             "depends_on": ["s1"]},
        ]
    },
}


def _gw() -> MCPGateway:
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    reg = ToolRegistry(store)
    CLIAdapter(reg, config_path=HERE / "adapters/cli_adapter/configs/cli_tools.yaml").discover()
    ScriptAdapter(reg, config_path=HERE / "adapters/script_adapter/configs/scripts.yaml").discover()
    audit = AuditLogger(AuditStore(sqlite=store))
    gateway = MCPGateway(reg, audit, workflow_engine=None)
    engine = WorkflowEngine(gateway)
    gateway.workflow = engine
    engine.register_workflows(WORKFLOWS)
    # 与 main.build_hub 一致：平台级虚拟工具注册进 registry（A1 修复）
    reg.register_tool("run_workflow", engine.tool_definition())
    return gateway


def test_tools_list_includes_run_workflow():
    gw = _gw()
    names = {t["name"] for t in gw.list_tools()["tools"]}
    assert "run_workflow" in names


def test_run_workflow_via_call():
    gw = _gw()
    res = gw.call({"name": "run_workflow", "arguments": {"workflow": "demo_flow"},
                   "caller": "it", "permission_level": "write"})
    assert res["isError"] is False
    summary = res["content"][0]["text"]
    import json
    data = json.loads(summary)
    assert data["workflow"] == "demo_flow"
    assert data["ok"] is True
    assert len(data["steps"]) == 2


def test_run_workflow_unknown_name():
    gw = _gw()
    res = gw.call({"name": "run_workflow", "arguments": {"workflow": "nope"},
                   "caller": "it", "permission_level": "write"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1002  # 参数校验（enum）


def test_run_workflow_read_permission_denied():
    gw = _gw()
    res = gw.call({"name": "run_workflow", "arguments": {"workflow": "demo_flow"},
                   "caller": "it", "permission_level": "read"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1003  # 运行工作流需要 write


def test_step_audit_recorded():
    gw = _gw()
    gw.call({"name": "run_workflow", "arguments": {"workflow": "demo_flow"},
             "caller": "it", "permission_level": "write"})
    rows = gw.audit.store.query(limit=20)
    tools = {r["tool"] for r in rows}
    assert "run_workflow" in tools       # 工作流本身
    assert "file_summary" in tools       # 每步也写入审计（不旁路）


def test_workflow_rate_limited():
    gw = _gw()
    gw.rate_limiter.reset("run_workflow", "ra")
    # 触发超过 10/m → 第 11 次被 1004 拦截
    for _ in range(10):
        gw.call({"name": "run_workflow", "arguments": {"workflow": "demo_flow"},
                 "caller": "ra", "permission_level": "write"})
    res = gw.call({"name": "run_workflow", "arguments": {"workflow": "demo_flow"},
                   "caller": "ra", "permission_level": "write"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1004
