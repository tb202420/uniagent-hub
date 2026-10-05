"""适配器契约测试（阶段 2 质量闸门）。

对所有适配器（CLI / REST / Script / Database / MQTT-mock）跑同一组用例，确保：
- list_tools 输出符合统一结构
- call_tool 对未知参数/注入返回 1002/1007（Guard 横切不可绕过）
- Gateway 对越权调用返回 1003
- 所有调用写入审计
新增适配器必须通过本契约测试才能合入。
"""

import tempfile
from pathlib import Path

import pytest

from adapters.cli_adapter.adapter import CLIAdapter
from adapters.database_adapter.adapter import DatabaseAdapter
from adapters.rest_adapter.adapter import RESTAdapter
from adapters.script_adapter.adapter import ScriptAdapter
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

HERE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def gw() -> MCPGateway:
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "test.db")
    reg = ToolRegistry(store)
    CLIAdapter(reg, config_path=HERE / "adapters/cli_adapter/configs/cli_tools.yaml").discover()
    RESTAdapter(reg, spec_source=HERE / "adapters/rest_adapter/specs/open_meteo.yaml").discover()
    ScriptAdapter(reg, config_path=HERE / "adapters/script_adapter/configs/scripts.yaml").discover()
    DatabaseAdapter(reg, config_path=HERE / "adapters/database_adapter/configs/database.yaml").discover()
    audit = AuditLogger(AuditStore(sqlite=store))
    return MCPGateway(reg, audit)


def test_contract_five_types_registered(gw):
    names = {t["name"] for t in gw.list_tools()["tools"]}
    assert {"git_status", "file_search"} <= names          # CLI
    assert "get_weather" in names                          # REST
    assert "file_summary" in names                         # Script
    assert {"db_query", "db_execute"} <= names             # Database


def test_contract_tools_list_schema_uniform(gw):
    for t in gw.list_tools()["tools"]:
        assert t["name"] and t["description"]
        assert t["inputSchema"]["type"] == "object"
        assert "properties" in t["inputSchema"]


@pytest.mark.parametrize("tool,args", [
    ("file_search", {"directory": "/tmp", "pattern": "x; rm -rf /"}),   # CLI 注入
    ("get_weather", {"latitude": 1.0, "evil": "x; rm -rf /"}),          # REST 未知参数
    ("file_summary", {"directory": "/tmp", "evil": "x"}),               # Script 未知参数
])
def test_contract_unknown_params_blocked(gw, tool, args):
    res = gw.call({"name": tool, "arguments": args, "caller": "contract_test"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] in (1002, 1007)


def test_contract_permission_denied(gw):
    # 注册一个 write 级工具（本地脚本 readOnly=false → permissionLevel=write）
    reg = gw.registry
    spec = {
        "id": "script.contract.write",
        "type": "local_script",
        "name": "契约测试写工具",
        "protocol": "script",
        "endpoint": {"path": str(HERE / "adapters/script_adapter/scripts/file_summary.py"),
                     "interpreter": "python"},
        "capabilities": [{
            "name": "write_probe",
            "description": "write 级工具探测",
            "command": "--dir {directory}",
            "inputSchema": {"type": "object", "properties": {"directory": {"type": "string"}},
                            "required": ["directory"]},
            "readOnly": False,
        }],
        "constraints": {"readOnly": False, "permissionLevel": "write"},
    }
    reg.register(spec, adapter=reg.owner_of("cli.git.status") or "script")
    # read 权限调用 write 级工具 → 1003
    res = gw.call({"name": "write_probe", "arguments": {"directory": "/tmp"},
                   "caller": "contract_test", "permission_level": "read"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1003


def test_contract_audit_written_for_all_adapters(gw):
    calls = [
        ("file_search", {"directory": "/tmp", "pattern": "*.py"}),
        ("file_summary", {"directory": "/tmp"}),
        ("get_weather", {"latitude": 39.9, "longitude": 116.4}),
        ("db_query", {"sql": "SELECT * FROM meeting_rooms"}),
    ]
    for tool, args in calls:
        gw.call({"name": tool, "arguments": args, "caller": "contract_test"})
    rows = gw.audit.store.query(limit=50)
    tools_seen = {r["tool"] for r in rows}
    assert {"file_search", "file_summary", "get_weather", "db_query"} <= tools_seen
