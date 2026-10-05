"""数据库适配器单元/集成测试（B9，第五类适配器）。

覆盖：注册（type=database）、只读查询、SQL 注入拦截（词法 + 白名单）、
写操作权限（gateway 1003）、写后可见、审计落盘。
"""

import tempfile
from pathlib import Path

import pytest

from adapters.database_adapter.adapter import DatabaseAdapter, _check_sql
from core.gateway.server import MCPGateway
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

HERE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def gw() -> MCPGateway:
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    reg = ToolRegistry(store)
    DatabaseAdapter(reg, config_path=HERE / "adapters/database_adapter/configs/database.yaml").discover()
    audit = AuditLogger(AuditStore(sqlite=store))
    return MCPGateway(reg, audit)


def test_registered_as_database_type(gw):
    specs = gw.registry.all_specs()
    db_specs = [s for s in specs if s.type == "database"]
    assert len(db_specs) == 2
    names = {c.name for s in db_specs for c in s.capabilities}
    assert names == {"db_query", "db_execute"}


def test_db_query_reads_seed_rows(gw):
    res = gw.call({"name": "db_query",
                   "arguments": {"sql": "SELECT * FROM meeting_rooms"},
                   "caller": "db_test"})
    assert res["isError"] is False
    text = res["content"][0]["text"]
    assert "Room301" in text and "31.0" in text


def test_db_query_injection_semicolon_blocked(gw):
    res = gw.call({"name": "db_query",
                   "arguments": {"sql": "SELECT * FROM meeting_rooms; DROP TABLE meeting_rooms"},
                   "caller": "db_test"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1007


def test_db_query_non_select_verb_blocked(gw):
    res = gw.call({"name": "db_query",
                   "arguments": {"sql": "DELETE FROM meeting_rooms"},
                   "caller": "db_test"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1007


def test_db_execute_requires_write(gw):
    res = gw.call({"name": "db_execute",
                   "arguments": {"sql": "UPDATE meeting_rooms SET status = 'ok' WHERE id = 1"},
                   "caller": "db_test", "permission_level": "read"})
    assert res["isError"] is True
    assert res["meta"]["error_code"] == 1003


def test_db_execute_write_visible_in_query(gw):
    res = gw.call({"name": "db_execute",
                   "arguments": {"sql": "UPDATE meeting_rooms SET status = 'ok' WHERE id = 1"},
                   "caller": "db_test", "permission_level": "write"})
    assert res["isError"] is False
    res = gw.call({"name": "db_query",
                   "arguments": {"sql": "SELECT status FROM meeting_rooms WHERE id = 1"},
                   "caller": "db_test"})
    assert "ok" in res["content"][0]["text"]


def test_db_audit_written(gw):
    rows = gw.audit.store.query(limit=50)
    assert "db_query" in {r["tool"] for r in rows}


@pytest.mark.parametrize("tool,sql,ok", [
    ("db_query", "SELECT * FROM meeting_rooms", True),
    ("db_query", "select count(*) from meeting_rooms", True),
    ("db_query", "SELECT * FROM meeting_rooms -- tail", False),
    ("db_query", "DELETE FROM meeting_rooms", False),
    ("db_execute", "INSERT INTO meeting_rooms (name, temperature, status) VALUES ('X', 1.0, 'ok')", True),
    ("db_execute", "SELECT * FROM meeting_rooms", False),
])
def test_sql_lexical_check(tool, sql, ok):
    err = _check_sql(tool, sql)
    assert (err is None) == ok