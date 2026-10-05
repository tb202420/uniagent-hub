"""数据库适配器（B9，第五类适配器）：把 SQLite 数据库封装为 MCP 工具。

注册 2 个能力（docs/unispec.md §6.5 示例）：
  db_query   —— 只读 SELECT 单语句（read 权限）
  db_execute —— 受限写 INSERT/UPDATE/DELETE 单语句（write 权限）

安全模型（纵深防御，与其他适配器同一套 Guard 管道）：
  1) Gateway Guard      —— readOnly/权限（db_execute 需 write）、限流、未知参数 1002
  2) 参数白名单          —— inputSchema.pattern 拒绝 `;` 反引号等注入元字符（1007）
  3) 词法校验（本层兜底）—— 单语句、动词白名单（query 仅 SELECT）、禁止 `--`/`/*` 注释
  4) 库隔离              —— 演示库 data/uniagent_demo.db 与 Hub 自身 uniagent.db 完全隔离
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from core.contracts import (
    CallContext, ToolResult,
    E_INJECTION_BLOCKED, E_INTERNAL, E_TOOL_NOT_FOUND,
)
from core.registry.registry import ToolRegistry

# SQL 参数白名单：字母数字/下划线/括号/点/逗号/星号/引号/比较符/空格/百分号。
# 显式排除 `;`（多语句）、反引号、双引号、`$` 等元字符。
_SQL_ARG_PATTERN = r"^[a-zA-Z0-9_().,*'=<>!+\- /%]+$"

# 动词白名单（词法校验兜底，防 schema 层放过后的绕过）
_VERBS = {
    "db_query": {"SELECT"},
    "db_execute": {"INSERT", "UPDATE", "DELETE"},
}
_COMMENT_RE = re.compile(r"--|/\*|\*/")

_LOCK = threading.Lock()  # SQLite 演示库单写连接（与 store.py 同款策略）


def _check_sql(tool_name: str, sql: str) -> str | None:
    """返回错误信息；None 表示通过。"""
    if _COMMENT_RE.search(sql):
        return "SQL 含注释（注入防护拦截）"
    if sql.count(";") > 0:
        return "仅允许单语句（注入防护拦截）"
    m = re.match(r"^\s*([A-Za-z]+)\b", sql)
    if not m or m.group(1).upper() not in _VERBS[tool_name]:
        allowed = "/".join(sorted(_VERBS[tool_name]))
        return f"仅允许 {allowed} 单语句"
    return None


class DatabaseAdapter:
    """实现 BaseAdapter 协议（discover / list_tools / call_tool）。"""

    def __init__(self, registry: ToolRegistry,
                 config_path: str | Path | None = None) -> None:
        self.registry = registry
        self.config_path = Path(config_path) if config_path else None
        self._db_path: Path | None = None
        self._tool_meta: dict[str, dict] = {}

    # ---- 生命周期回调（改进方案 §4，可选实现）----

    def on_health_check(self) -> dict:
        """数据库可达性检查（SELECT 1；连接失败不影响 /healthz 响应）。"""
        ok = False
        if self._db_path is not None:
            try:
                with _LOCK:
                    conn = sqlite3.connect(str(self._db_path), timeout=3)
                    try:
                        conn.execute("SELECT 1").fetchone()
                        ok = True
                    finally:
                        conn.close()
            except sqlite3.Error:
                ok = False
        return {"ok": ok, "db_path": str(self._db_path or "")}

    # ---- 注册（discover）----

    def discover(self) -> list[dict]:
        if self.config_path is None:
            return []
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        cfg = raw.get("database", {})
        db_path = Path(cfg.get("db_path") or "data/uniagent_demo.db")
        if not db_path.is_absolute():
            db_path = self.config_path.parents[3] / db_path  # 相对路径以仓库根为准
        self._db_path = db_path.resolve()
        self._seed(cfg.get("seed") or {})

        specs: list[dict] = []
        for tool_cfg in cfg.get("tools", []):
            name = tool_cfg["name"]
            self._tool_meta[name] = tool_cfg
            spec = self._tool_to_unispec(name, tool_cfg)
            self.registry.register(spec, adapter=self)
            specs.append(spec)
        return specs

    def _seed(self, seed_cfg: dict) -> None:
        """建表 + 播种（仅当表为空 / 文件不存在，幂等）。"""
        ddl, rows = seed_cfg.get("ddl"), seed_cfg.get("rows") or []
        if not ddl:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()
        if not rows:
            return
        conn = sqlite3.connect(str(self._db_path))
        try:
            table = seed_cfg.get("table", "meeting_rooms")
            empty = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            if empty:
                placeholders = ",".join("?" * len(rows[0]))
                conn.executemany(
                    f"INSERT INTO {table} "
                    f"({','.join(self._seed_cols(ddl))}) VALUES ({placeholders})",
                    rows)
                conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _seed_cols(ddl: str) -> list[str]:
        """从 DDL 粗略解析列名（演示配置固定，仅用于播种占位）。"""
        cols: list[str] = []
        for name, kind in re.findall(r"(\w+)\s+(TEXT|REAL|INTEGER)", ddl):
            if name.lower() != "id":
                cols.append(name)
        return cols

    def _tool_to_unispec(self, name: str, tool_cfg: dict) -> dict:
        """工具配置 → UniSpec dict（type=database / protocol=sqlite）。"""
        read_only = bool(tool_cfg.get("readOnly", True))
        return {
            "id": f"db.demo.{name}",
            "type": "database",
            "name": f"演示数据库·{name}",
            "description": tool_cfg.get("description"),
            "protocol": "sqlite",
            "endpoint": {"path": str(self._db_path), "engine": "sqlite"},
            "capabilities": [{
                "name": name,
                "title": name,
                "description": tool_cfg.get("description"),
                "command": None,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string",
                                "description": "SQL 单语句（无分号/注释）",
                                "pattern": _SQL_ARG_PATTERN},
                    },
                    "required": ["sql"],
                },
                "outputSchema": {"type": "array"},
                "readOnly": read_only,
                "rateLimit": tool_cfg.get("rateLimit"),
                "permissionLevel": tool_cfg.get("permissionLevel"),
            }],
            "constraints": {
                "readOnly": read_only,
                "permissionLevel": tool_cfg.get("permissionLevel", "read"),
                "rateLimit": tool_cfg.get("rateLimit"),
                "timeout": "5s",
            },
        }

    # ---- 查询（list_tools）----

    def list_tools(self) -> list[dict]:
        return self.registry.list_tools()

    # ---- 执行（call_tool）----

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        if name not in _VERBS:
            return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                              error_msg=f"工具不存在: {name}")
        sql = (args or {}).get("sql", "").strip()
        # 词法兜底校验（schema 白名单之外的第二道防线）
        err = _check_sql(name, sql)
        if err:
            return ToolResult(ok=False, error_code=E_INJECTION_BLOCKED,
                              error_msg=err)
        start = time.perf_counter()
        try:
            with _LOCK:
                conn = sqlite3.connect(str(self._db_path), timeout=3)
                conn.row_factory = sqlite3.Row
                try:
                    if name == "db_query":
                        rows = [dict(r) for r in conn.execute(sql).fetchall()]
                        data = json.dumps(rows, ensure_ascii=False)
                    else:
                        cur = conn.execute(sql)
                        conn.commit()
                        data = json.dumps({"affected": max(cur.rowcount or 0, 1)},
                                          ensure_ascii=False)
                finally:
                    conn.close()
        except sqlite3.Error as e:
            return ToolResult(ok=False, error_code=E_INTERNAL,
                              error_msg=f"SQL 执行失败: {e}")
        latency = int((time.perf_counter() - start) * 1000)
        return ToolResult(ok=True, data=data, latency_ms=latency)