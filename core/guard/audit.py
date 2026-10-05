"""审计日志（Guard 强制写入，docs/api.md §5 字段契约）。

双写过渡：JSONL 文件（便于 grep 调试）+ SQLite 表（阶段 2 起作为查询源）。

改进方案 §5.3 安全增强（本文件实现两项，均为**默认关闭的可选能力**）：
- `schema_hash`：每条审计记录携带被调工具的 Schema 内容哈希（工具投毒防护的可追溯性，
  见 core/guard/attestation.py）；由 Gateway 在 record 时写入（默认始终开启）。
- **审计哈希链**（`HUB_AUDIT_CHAIN=1`）：逐条 `rec_hash = sha256(pre_hash + 记录内容)`，
  任意一条被篡改都会在 `verify_chain` 校验中暴露（防篡改、可验证）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("uniagent.audit")
_log_lock = threading.Lock()


def canonical_json(obj: Any) -> str:
    """规范化 JSON（与 attestation 模块一致的哈希稳定性约定）。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def chain_hash(pre_hash: str, record: dict[str, Any]) -> str:
    """单条记录链式哈希：sha256(pre_hash + 记录内容（不含 rec_hash 自身）)。"""
    payload = {k: v for k, v in record.items() if k != "rec_hash"}
    return hashlib.sha256(
        (pre_hash + canonical_json(payload)).encode("utf-8")).hexdigest()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """读取 JSONL 审计文件为记录列表（空行忽略）。"""
    text = Path(path).read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def last_record_hash(path: str | Path) -> str:
    """读取 JSONL 文件最后一条记录的 rec_hash（用于进程重启后接续链）。"""
    p = Path(path)
    if not p.exists():
        return ""
    last = ""
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    if not last:
        return ""
    try:
        return str(json.loads(last).get("rec_hash", "") or "")
    except json.JSONDecodeError:
        return ""


def verify_chain(records: list[dict[str, Any]]) -> tuple[bool, int | None, str]:
    """校验哈希链完整性（混合文件兼容，A1 修复）。

    返回 (是否完好, 首个问题记录下标(全局), 说明)。
    判据：链段内 ① pre_hash 必须等于上一条 rec_hash；② rec_hash 必须等于重算值。

    混合文件语义：切出所有"含 rec_hash 的连续链段"逐段校验；
    段间的无链记录（链启用前/关闭期的历史记录）直接跳过、**不报错**，
    并在说明中注明跳过条数。注意：被移除 rec_hash 的记录无法与"未启用链"
    区分 —— 链只对其覆盖范围内的记录提供防篡改保证（文档化语义）。
    """
    if not records:
        return True, None, "ok"
    skipped = 0
    i, n = 0, len(records)
    while i < n:
        if not records[i].get("rec_hash"):
            skipped += 1          # 无链记录（历史/关链期）跳过
            i += 1
            continue
        prev = str(records[i].get("pre_hash", "") or "")
        while i < n and records[i].get("rec_hash"):
            rec = records[i]
            pre = str(rec.get("pre_hash", "") or "")
            if pre != prev:
                return False, i, f"第 {i} 条 pre_hash 断链（期望 {prev[:12]}…，实际 {pre[:12]}…）"
            expected = chain_hash(pre, rec)
            if rec.get("rec_hash") != expected:
                return False, i, f"第 {i} 条内容被篡改（rec_hash 不匹配）"
            prev = str(rec["rec_hash"])
            i += 1
    msg = "ok" + (f"（跳过 {skipped} 条未启用链的记录）" if skipped else "")
    return True, None, msg


class AuditStore:
    """审计存储：JSONL 文件 + 内存 ring（供查询 API / 界面使用）+ 可选 SQLite。"""

    def __init__(self, path: str | Path | None = None, max_memory: int = 2000,
                 sqlite: Any = None, chain: bool | None = None) -> None:
        self._path = Path(path) if path else None
        self._ring: list[dict[str, Any]] = []
        self._max = max_memory
        self.sqlite = sqlite  # core.registry.store.SQLiteStore 实例（可选，双写）
        # 哈希链：显式参数 > 环境变量 HUB_AUDIT_CHAIN > 默认关闭
        self.chain_enabled = _env_truthy("HUB_AUDIT_CHAIN") if chain is None else chain
        self._last_hash = ""
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self.chain_enabled:
                # 进程重启后从文件尾部接续（跨会话保持单一完整链）
                self._last_hash = last_record_hash(self._path)

    def write(self, record: dict[str, Any]) -> None:
        with _log_lock:
            if self.chain_enabled:
                record = self._chain(record)
            self._ring.append(record)
            if len(self._ring) > self._max:
                self._ring.pop(0)
            if self._path:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            if self.sqlite is not None:
                self.sqlite.append_audit(record)
        logger.info("audit %s", json.dumps(record, ensure_ascii=False))

    def _chain(self, record: dict[str, Any]) -> dict[str, Any]:
        """附加 pre_hash / rec_hash（就地复制，不修改调用方对象）。"""
        rec = dict(record)
        rec["pre_hash"] = self._last_hash
        rec["rec_hash"] = chain_hash(self._last_hash, rec)
        self._last_hash = rec["rec_hash"]
        return rec

    def verify_file(self) -> tuple[bool, int | None, str]:
        """校验本存储对应的 JSONL 文件哈希链（无文件返回 ok）。"""
        if not self._path or not self._path.exists():
            return True, None, "ok（无审计文件）"
        return verify_chain(read_jsonl(self._path))

    def query(self, limit: int = 100, tool: str | None = None) -> list[dict[str, Any]]:
        """优先查 SQLite（可按 tool + 时间范围），否则回退内存 ring。"""
        if self.sqlite is not None:
            rows = self.sqlite.query_audit(tool=tool, limit=limit)
            return [self._normalize_sqlite_row(r) for r in rows]
        with _log_lock:
            rows = [r for r in self._ring if tool is None or r.get("tool") == tool]
        return list(reversed(rows[-limit:]))

    @staticmethod
    def _normalize_sqlite_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": row.get("trace_id"),
            "ts": row.get("ts"),
            "caller": row.get("caller"),
            "tool": row.get("tool_name"),
            "args": json.loads(row.get("args_json") or "{}"),
            "guard_result": row.get("guard_result"),
            "result": json.loads(row.get("result_json") or "{}"),
            "latency_ms": row.get("latency_ms"),
            "error_code": row.get("error_code"),
            "schema_hash": row.get("schema_hash"),
            "pre_hash": row.get("pre_hash"),
            "rec_hash": row.get("rec_hash"),
        }


class AuditLogger:
    """审计记录构造器：统一填充 trace_id / ts / caller 等字段。"""

    def __init__(self, store: AuditStore) -> None:
        self.store = store

    def record(self, *, trace_id: str, caller: str, tool: str, args: dict,
               guard_result: str, result: dict, latency_ms: int,
               block_reason: str = "", error_code: int = 0,
               schema_hash: str = "") -> None:
        """构造审计记录。

        error_code：拦截/失败时的数字错误码（1001/1002/1003/1004/1005/1006/1007/1999，
        docs/api.md §4）。A2 修复：此前该字段缺失，SQLite audit.error_code 列恒为 0，
        Dashboard 无法按错误码检索；现在由 Gateway Guard 管道在 record 时写入。

        schema_hash（改进方案 §5.1）：被调工具定义的内容哈希（工具投毒防护追溯）。
        """
        rec = {
            "trace_id": trace_id,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "caller": caller,
            "tool": tool,
            "args": args,
            "guard_result": guard_result,   # passed | blocked
            "block_reason": block_reason,
            "result": result,
            "latency_ms": latency_ms,
            "error_code": error_code,
            "schema_hash": schema_hash,
        }
        self.store.write(rec)


_default_store = AuditStore(path=os.environ.get("HUB_AUDIT_FILE", "data/audit.jsonl"))
default_logger = AuditLogger(_default_store)