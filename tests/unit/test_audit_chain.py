"""审计哈希链与 schema_hash 字段测试（改进方案 §5）。"""

import json

from core.guard.audit import (
    AuditLogger, AuditStore, chain_hash, read_jsonl, verify_chain,
)


def _kw(trace: str, tool: str = "git_status"):
    """AuditLogger.record 的合法关键字参数（不含 ts，由记录器生成）。"""
    return {"trace_id": trace, "caller": "t", "tool": tool, "args": {},
            "guard_result": "passed", "block_reason": "", "result": {"ok": True},
            "latency_ms": 1, "error_code": 0}


def test_chain_records_and_verify(tmp_path):
    logger = AuditLogger(AuditStore(path=tmp_path / "audit.jsonl", chain=True))
    for i in range(3):
        logger.record(**_kw(f"t{i}"))
    records = read_jsonl(tmp_path / "audit.jsonl")
    assert len(records) == 3
    assert records[0]["pre_hash"] == ""
    assert records[1]["pre_hash"] == records[0]["rec_hash"]
    assert records[2]["pre_hash"] == records[1]["rec_hash"]
    ok, idx, msg = verify_chain(records)
    assert ok is True and idx is None


def test_chain_survives_restart(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLogger(AuditStore(path=path, chain=True)).record(**_kw("a"))
    AuditLogger(AuditStore(path=path, chain=True)).record(**_kw("b"))
    records = read_jsonl(path)
    assert records[1]["pre_hash"] == records[0]["rec_hash"]  # 跨进程接续
    assert verify_chain(records)[0] is True


def test_chain_detects_tamper(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(AuditStore(path=path, chain=True))
    for i in range(3):
        logger.record(**_kw(f"t{i}"))
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["caller"] = "hacker"                     # 篡改第 2 条
    lines[1] = json.dumps(rec, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, idx, msg = verify_chain(read_jsonl(path))
    assert ok is False
    assert idx == 1
    assert "篡改" in msg


def test_chain_disabled_by_default(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLogger(AuditStore(path=path)).record(**_kw("t0"))
    assert "rec_hash" not in read_jsonl(path)[0]


def test_chain_hash_ignores_own_field():
    rec = {"trace_id": "t", "tool": "x", "args": {}}
    h = chain_hash("pre", rec)
    assert len(h) == 64
    assert chain_hash("pre", {**rec, "rec_hash": "ignored"}) == h


def test_mixed_file_skips_leading_unchained(tmp_path):
    """混合文件兼容：链启用前的历史记录（无 rec_hash）跳过，链段本身仍可校验。"""
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(AuditStore(path=path, chain=False))
    logger.record(**_kw("old1"))               # 历史记录（无链）
    logger.record(**_kw("old2"))
    chain_logger = AuditLogger(AuditStore(path=path, chain=True))
    chain_logger.record(**_kw("new1"))         # 链启用后
    chain_logger.record(**_kw("new2"))
    records = read_jsonl(path)
    ok, idx, msg = verify_chain(records)
    assert ok is True and idx is None
    # 篡改链段 → 检出
    records[3]["caller"] = "hacker"
    ok2, idx2, _ = verify_chain(records)
    assert ok2 is False and idx2 == 3


def test_mixed_file_multiple_segments(tmp_path):
    """A1 修复：链段 → 关链期 → 再启链 的混合文件不应误报"篡改"。"""
    path = tmp_path / "audit.jsonl"
    lg = AuditLogger(AuditStore(path=path, chain=True))
    lg.record(**_kw("a1"))
    lg.record(**_kw("a2"))                       # 链段 1
    plain = AuditLogger(AuditStore(path=path, chain=False))
    plain.record(**_kw("b1"))
    plain.record(**_kw("b2"))                    # 关链期（无 rec_hash）
    lg2 = AuditLogger(AuditStore(path=path, chain=True))
    lg2.record(**_kw("c1"))
    lg2.record(**_kw("c2"))                      # 链段 2
    records = read_jsonl(path)
    ok, idx, msg = verify_chain(records)
    assert ok is True and idx is None
    assert "跳过 2 条" in msg                     # 中性提示，不报错
    # 链段 2 内部篡改 → 全局下标精确定位
    records[5]["caller"] = "hacker"              # c2
    ok2, idx2, _ = verify_chain(records)
    assert ok2 is False and idx2 == 5


def test_record_carries_schema_hash(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(AuditStore(path=path))
    logger.record(**_kw("t0"), schema_hash="abc123")
    assert read_jsonl(path)[0]["schema_hash"] == "abc123"