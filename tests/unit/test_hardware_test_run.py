"""硬件用例执行器判据单测（A2 修复：TG-3 判据顺序无关）。"""

from core.guard.audit import AuditLogger, AuditStore
from scripts.hardware_test_run import Runner


def _rec(trace: str, tool: str, schema_hash: str):
    return {"trace_id": trace, "caller": "t", "tool": tool, "args": {},
            "guard_result": "passed", "block_reason": "",
            "result": {"ok": True}, "latency_ms": 1, "error_code": 0,
            "schema_hash": schema_hash}


def test_tg3_order_independent_mixed(tmp_path):
    """链路中包含旧版元层记录（schema_hash 为空）时 TG-3 仍应通过。

    该情形对应 TG-4（元工具）执行之后重跑 TG-3 的历史顺序依赖问题：
    判据按工具名分组、排除元工具名，不再受最近 N 条影响。
    """
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(AuditStore(path=path, chain=True))
    logger.record(**_rec("t1", "get_system_cpu", "abc123"))
    logger.record(**_rec("t2", "execute_tool", ""))       # A2 修复前的元层记录形态
    logger.record(**_rec("t3", "plug_get_state", "def456"))

    runner = Runner("http://127.0.0.1:1")                 # 无需真实 Hub（tg3 只读文件）
    ok, detail = runner.tg3(str(path))
    assert ok is True, detail
    assert "非元工具缺schema_hash=无" in detail           # execute_tool 被排除


def test_tg3_fails_on_missing_hash_for_regular_tool(tmp_path):
    """普通工具缺 schema_hash 时 TG-3 必须判 FAIL（判据仍有效）。"""
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(AuditStore(path=path, chain=True))
    logger.record(**_rec("t1", "get_system_cpu", "abc123"))
    logger.record(**_rec("t2", "plug_get_state", ""))     # 普通工具缺哈希 → 判 FAIL
    runner = Runner("http://127.0.0.1:1")
    ok, detail = runner.tg3(str(path))
    assert ok is False
    assert "plug_get_state" in detail


def test_tg3_missing_file(tmp_path):
    runner = Runner("http://127.0.0.1:1")
    ok, detail = runner.tg3(str(tmp_path / "nope.jsonl"))
    assert ok is False and "不存在" in detail