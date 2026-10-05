"""SQLiteStore 单元测试。"""

import json
import tempfile
from pathlib import Path

from core.registry.store import SQLiteStore

SPEC = {
    "id": "cli.git.status", "type": "cli_tool", "name": "Git",
    "protocol": "subprocess",
    "capabilities": [{"name": "git_status", "description": "d",
                      "command": "git status --short"}],
}


def test_upsert_and_load():
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    store.upsert_spec(SPEC)
    specs = store.load_all_specs()
    assert specs[0]["id"] == "cli.git.status"


def test_delete_spec():
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    store.upsert_spec(SPEC)
    store.delete_spec("cli.git.status")
    assert store.load_all_specs() == []


def test_upsert_overwrite():
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    store.upsert_spec(SPEC)
    store.upsert_spec({**SPEC, "name": "Git v2"})
    assert store.load_all_specs()[0]["name"] == "Git v2"


def test_audit_roundtrip():
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    rec = {
        "trace_id": "abc123", "tool": "git_status", "caller": "test",
        "args": {"repo_path": "x"}, "result": {"ok": True},
        "guard_result": "passed", "latency_ms": 5, "ts": "2026-09-25T12:00:00Z",
    }
    store.append_audit(rec)
    rows = store.query_audit(tool="git_status")
    assert rows[0]["trace_id"] == "abc123"
    assert rows[0]["tool_name"] == "git_status"
    assert json.loads(rows[0]["args_json"])["repo_path"] == "x"


def test_query_filter_since():
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    store.append_audit({"trace_id": "t1", "tool": "a", "caller": "c",
                        "args": {}, "result": {"ok": True}, "guard_result": "passed",
                        "latency_ms": 1, "ts": "2026-09-25T10:00:00Z"})
    store.append_audit({"trace_id": "t2", "tool": "a", "caller": "c",
                        "args": {}, "result": {"ok": True}, "guard_result": "passed",
                        "latency_ms": 1, "ts": "2026-09-25T11:00:00Z"})
    rows = store.query_audit(since_ts="2026-09-25T10:30:00Z")
    assert [r["trace_id"] for r in rows] == ["t2"]


def test_wal_mode_enabled():
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_audit_duplicate_trace_id_kept():
    """BE-5：主键为自增 id，trace_id 重复不再吞掉历史记录（OR REPLACE 已移除）。"""
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    rec = {"tool": "a", "caller": "c", "args": {}, "result": {"ok": True},
           "guard_result": "passed", "latency_ms": 1, "ts": "2026-09-25T10:00:00Z"}
    store.append_audit({**rec, "trace_id": "dup"})
    store.append_audit({**rec, "trace_id": "dup"})
    rows = store.query_audit()
    assert len(rows) == 2
    assert rows[0]["id"] > rows[1]["id"]          # 自增主键：插入序可追溯


def test_audit_legacy_schema_migration():
    """BE-5：老库（trace_id 主键、无 id 列）打开时自动迁移，历史记录全量保留。"""
    import sqlite3
    db = Path(tempfile.mkdtemp()) / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE audit (
        trace_id TEXT PRIMARY KEY, tool_name TEXT, caller TEXT, args_json TEXT,
        result_json TEXT, is_error INTEGER, error_code INTEGER,
        guard_result TEXT, latency_ms REAL, ts TEXT)""")
    conn.execute("INSERT INTO audit VALUES"
                 "('t1','a','c','{}','{}',0,0,'passed',1,'2026-09-25T10:00:00Z')")
    conn.commit()
    conn.close()
    store = SQLiteStore(db)
    rows = store.query_audit()
    assert [r["trace_id"] for r in rows] == ["t1"]
    store.append_audit({"trace_id": "t2", "tool": "a", "caller": "c",
                        "args": {}, "result": {"ok": True}, "guard_result": "passed",
                        "latency_ms": 1, "ts": "2026-09-25T11:00:00Z"})
    assert len(store.query_audit()) == 2          # 迁移后可继续追加


def test_audit_stats_sql_aggregation():
    """UI-3：概览统计走 SQL 聚合（total / ok / avg_latency）。"""
    store = SQLiteStore(Path(tempfile.mkdtemp()) / "t.db")
    for i, ok in enumerate((True, True, False)):
        store.append_audit({"trace_id": f"t{i}", "tool": "a", "caller": "c",
                            "args": {}, "result": {"ok": ok},
                            "guard_result": "passed" if ok else "blocked",
                            "latency_ms": 10 * (i + 1),
                            "ts": "2026-09-25T10:00:00Z"})
    stats = store.audit_stats()
    assert stats["total"] == 3
    assert stats["ok"] == 2
    assert abs(stats["avg_latency"] - 20.0) < 1e-6
