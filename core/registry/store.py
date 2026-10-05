"""SQLite 存储（阶段 2）：工具 UniSpec 持久化 + 审计落库。

- WAL 模式（PRAGMA journal_mode=WAL）避免并发写锁
- tools 表存完整 UniSpec（json 字段，不依赖 SQLite JSON1 扩展）
- audit 表存每次调用记录（与 data/audit.jsonl 双写过渡）
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tools (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    spec_json  TEXT NOT NULL,
    enabled    INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id     TEXT,
    tool_name    TEXT,
    caller       TEXT,
    args_json    TEXT,
    result_json  TEXT,
    is_error     INTEGER,
    error_code   INTEGER,
    guard_result TEXT,
    latency_ms   REAL,
    ts           TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_tool_ts ON audit(tool_name, ts);
CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit(trace_id);
"""

# 增量列迁移（改进方案 §5）：老库 ALTER TABLE 补齐，无需重建
_AUDIT_EXTRA_COLUMNS = {
    "schema_hash": "TEXT",   # 被调工具 Schema 内容哈希（工具投毒防护追溯）
    "pre_hash": "TEXT",      # 审计哈希链（HUB_AUDIT_CHAIN=1 时写入）
    "rec_hash": "TEXT",
}


class SQLiteStore:
    """线程安全（单连接 + 锁）的 SQLite 存储。"""

    def __init__(self, db_path: str | Path, audit_ttl_days: int = 30) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.audit_ttl_days = audit_ttl_days
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
            self._migrate_audit_columns()
            self._migrate_audit_pk()
            self._conn.commit()

    def _migrate_audit_columns(self) -> None:
        """向前兼容迁移：为已存在的 audit 表补齐新增列（幂等）。"""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(audit)")}
        for name, typ in _AUDIT_EXTRA_COLUMNS.items():
            if name not in cols:
                self._conn.execute(f"ALTER TABLE audit ADD COLUMN {name} {typ}")

    def _migrate_audit_pk(self) -> None:
        """BE-5：老库 audit 以 trace_id 为主键 → 迁移为 id 自增主键（幂等）。

        trace_id 由客户端提示产生、可能重复，作为主键时 INSERT OR REPLACE
        会静默覆盖同 trace_id 的历史审计记录；迁移后每条调用独立成行，
        trace_id 降级为普通关联键（索引查询）。迁移保留全量历史记录（按
        原插入序 rowid 重排，自增 id 与时间序一致）。
        """
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(audit)")}
        if not cols or "id" in cols:
            return
        self._conn.execute("ALTER TABLE audit RENAME TO audit_legacy")
        # 重建基础表（含 id 自增）并补齐增量列；索引名仍被 legacy 表占用，
        # 需在 DROP 后再跑一遍建表脚本重建索引
        self._conn.executescript(_SCHEMA)
        self._migrate_audit_columns()
        self._conn.execute(
            """INSERT INTO audit(trace_id, tool_name, caller, args_json, result_json,
                                 is_error, error_code, guard_result, latency_ms, ts,
                                 schema_hash, pre_hash, rec_hash)
               SELECT trace_id, tool_name, caller, args_json, result_json,
                      is_error, error_code, guard_result, latency_ms, ts,
                      schema_hash, pre_hash, rec_hash
               FROM audit_legacy ORDER BY rowid""")
        self._conn.execute("DROP TABLE audit_legacy")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- tools ----

    def upsert_spec(self, spec: dict[str, Any]) -> None:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = (
            spec["id"], spec["type"], spec["name"],
            json.dumps(spec, ensure_ascii=False),
            1, now, now,
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO tools(id, type, name, spec_json, enabled, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     type=excluded.type, name=excluded.name, spec_json=excluded.spec_json,
                     updated_at=excluded.updated_at""",
                row,
            )
            self._conn.commit()

    def delete_spec(self, resource_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM tools WHERE id=?", (resource_id,))
            self._conn.commit()

    def load_all_specs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT spec_json FROM tools WHERE enabled=1").fetchall()
        return [json.loads(r["spec_json"]) for r in rows]

    # ---- audit ----

    def append_audit(self, rec: dict[str, Any]) -> None:
        row = (
            rec["trace_id"], rec["tool"], rec["caller"],
            json.dumps(rec.get("args", {}), ensure_ascii=False),
            json.dumps(rec.get("result", {}), ensure_ascii=False),
            1 if not rec.get("result", {}).get("ok", True) else 0,
            rec.get("error_code", 0),
            rec["guard_result"], rec.get("latency_ms", 0), rec["ts"],
            rec.get("schema_hash", ""), rec.get("pre_hash", ""),
            rec.get("rec_hash", ""),
        )
        with self._lock:
            # BE-5：普通 INSERT（自增 id 主键），trace_id 重复不再覆盖历史记录
            self._conn.execute(
                """INSERT INTO audit
                   (trace_id, tool_name, caller, args_json, result_json,
                    is_error, error_code, guard_result, latency_ms, ts,
                    schema_hash, pre_hash, rec_hash)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                row,
            )
            self._conn.commit()

    def query_audit(self, tool: str | None = None, caller: str | None = None,
                    since_ts: str | None = None,
                    error_code: int | None = None,
                    limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit"
        conds, params = [], []
        if tool:
            conds.append("tool_name=?")
            params.append(tool)
        if caller:  # UI-2 修复：caller 在 SQL 层过滤，避免 LIMIT 截断后漏检
            conds.append("caller=?")
            params.append(caller)
        if since_ts:
            conds.append("ts>=?")
            params.append(since_ts)
        if error_code is not None:  # A2 修复：Dashboard 按错误码筛选（1007/1003/1004）
            conds.append("error_code=?")
            params.append(error_code)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        # 按 id（插入序）倒序：同秒记录不再依赖 ts 歧义排序
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def audit_stats(self) -> dict[str, Any]:
        """概览统计在 SQL 层聚合（UI-3：COUNT/SUM/AVG，不再拉全量记录到 Python）。"""
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*) AS total,
                          COALESCE(SUM(CASE WHEN is_error=0 THEN 1 ELSE 0 END), 0) AS ok_count,
                          COALESCE(AVG(COALESCE(latency_ms, 0)), 0) AS avg_latency
                   FROM audit""").fetchone()
        return {"total": row["total"], "ok": row["ok_count"],
                "avg_latency": float(row["avg_latency"])}

    def cleanup_audit(self) -> int:
        """清理超过 TTL 的审计记录（防膨胀）。返回删除行数。"""
        import datetime
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(days=self.audit_ttl_days)).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM audit WHERE ts<?", (cutoff,))
            self._conn.commit()
            return cur.rowcount
