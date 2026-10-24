"""Dashboard JSON API（SPA 数据源）与网关 /workflows/defs 集成测试。"""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from core.gateway.server import MCPGateway, create_app
from core.guard.audit import AuditLogger, AuditStore
from core.registry.registry import ToolRegistry
from core.workflow.engine import WorkflowEngine
from web.audit_dashboard.app import create_dashboard


def _db(tmp: str) -> Path:
    return Path(tmp) / "dash.db"


def _seed(tmp: str) -> None:
    from core.registry.store import SQLiteStore
    store = SQLiteStore(_db(tmp))
    base = {"tool": "t", "caller": "c", "args": {}, "guard_result": "blocked",
            "latency_ms": 5, "ts": "2026-10-24T10:00:00Z"}
    store.append_audit({**base, "trace_id": "a1", "result": {"ok": False},
                        "error_code": 1007})
    store.append_audit({**base, "trace_id": "a2", "result": {"ok": False},
                        "error_code": 1007})
    store.append_audit({**base, "trace_id": "a3", "result": {"ok": False},
                        "error_code": 1003})
    ok = {**base, "guard_result": "passed", "result": {"ok": True}}
    store.append_audit({**ok, "trace_id": "a4"})
    store.append_audit({**ok, "trace_id": "a5"})


def test_api_stats_aggregation(tmp_path=None):
    tmp = tempfile.mkdtemp()
    _seed(tmp)
    client = TestClient(create_dashboard(db_path=_db(tmp)))
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5 and body["ok"] == 2
    blocked = {b["error_code"]: b["count"] for b in body["blocked_by_error"]}
    assert blocked == {1007: 2, 1003: 1}     # 拦截按错误码聚合（安全中心数据源）
    assert body["tools"] == 0                # Hub 未启动时优雅降级，不报错


def test_api_audit_filter_by_error_code():
    tmp = tempfile.mkdtemp()
    _seed(tmp)
    client = TestClient(create_dashboard(db_path=_db(tmp)))
    body = client.get("/api/audit", params={"error_code": 1007}).json()
    assert len(body["items"]) == 2
    assert all(r["error_code"] == 1007 for r in body["items"])


def test_api_workflows_defs_via_hub():
    """网关 /workflows/defs：返回蓝图结构（SPA 可视化数据源）。"""
    reg = ToolRegistry()
    gw = MCPGateway(reg, AuditLogger(AuditStore(max_memory=50)))
    engine = WorkflowEngine(gw)
    engine.register_workflows({"demo_flow": {"steps": [
        {"id": "s1", "tool": "get_temperature", "args": {}},
        {"id": "s2", "tool": "ac_control", "depends_on": ["s1"],
         "condition": "{{s1.output}} > 28"}]}})
    gw.workflow = engine
    client = TestClient(create_app(reg, gateway=gw))
    body = client.get("/workflows/defs").json()
    assert body["items"][0]["name"] == "demo_flow"
    steps = body["items"][0]["steps"]
    assert steps[1]["depends_on"] == ["s1"]
    assert steps[1]["condition"] == "{{s1.output}} > 28"


def test_workflows_defs_protected_by_bearer(monkeypatch):
    """启用 HUB_API_TOKEN 后 /workflows/defs 与 /workflows/recent 同受 Bearer 保护。"""
    monkeypatch.setenv("HUB_API_TOKEN", "tok-1")
    reg = ToolRegistry()
    gw = MCPGateway(reg, AuditLogger(AuditStore(max_memory=50)))
    gw.workflow = WorkflowEngine(gw)
    app = create_app(reg, gateway=gw)
    monkeypatch.delenv("HUB_API_TOKEN")
    client = TestClient(app)
    assert client.get("/workflows/defs").status_code == 401
    ok = client.get("/workflows/defs", headers={"Authorization": "Bearer tok-1"})
    assert ok.status_code == 200 and ok.json() == {"items": []}


def test_api_audit_verify_chain(tmp_path=None):
    """/api/audit/verify：哈希链完好 → ok；篡改一条 → 定位失败。"""
    import tempfile
    from core.guard.audit import AuditStore

    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "audit.jsonl"
    store = AuditStore(path=path, chain=True, max_memory=10)
    for i in range(3):
        store.write({"trace_id": f"t{i}", "tool": "x", "caller": "c",
                     "args": {}, "guard_result": "passed",
                     "result": {"ok": True}, "latency_ms": 1,
                     "ts": "2026-10-24T10:00:00Z"})

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HUB_AUDIT_FILE", str(path))
        client = TestClient(create_dashboard(db_path=Path(tmp) / "d.db"))
        body = client.get("/api/audit/verify").json()
        assert body["ok"] is True

        # 篡改第二条的 tool 字段 → 链校验失败并定位
        lines = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["tool"] = "tampered"
        lines[1] = json.dumps(rec, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        body = client.get("/api/audit/verify").json()
        assert body["ok"] is False and body["first_bad"] is not None
