"""HITL 审批 Broker 单元测试（v3.0 批次）。"""

import threading
import time

from core.gateway.event_bus import EventBus
from core.guard.audit import AuditLogger, AuditStore, verify_chain
from core.guard.hitl import ApprovalBroker, describe_tool, approval_options


class _Cap:
    def __init__(self, read_only=False):
        self.readOnly = read_only


def test_requires_only_write_targets():
    broker = ApprovalBroker(tools={"control_pump"}, timeout=1, bus=EventBus())
    assert broker.requires("control_pump", _Cap(), "write") is True
    assert broker.requires("control_pump", _Cap(), "read") is False
    assert broker.requires("control_pump", _Cap(read_only=True), "write") is False
    assert broker.requires("get_soil_moisture", _Cap(), "write") is False


def test_wildcard_requires_all_writes():
    broker = ApprovalBroker(tools={"*"}, timeout=1, bus=EventBus())
    assert broker.requires("ac_control", _Cap(), "write") is True


def test_natural_language_summary_and_options():
    assert describe_tool("control_pump", {"action": "on", "duration": 300}) == \
        "AI 想启动水泵 300 秒，是否允许？"
    assert describe_tool("control_pump", {"action": "off"}) == "AI 想关闭水泵，是否允许？"
    opts = approval_options("control_pump", {"action": "on", "duration": 300})
    assert [o["key"] for o in opts] == ["approve", "reject", "modify"]
    assert opts[2]["override_args"] == {"action": "on", "duration": 60}


def test_approve_unblocks_waiter():
    broker = ApprovalBroker(tools={"control_pump"}, timeout=2, bus=EventBus())
    req = broker.request(tool="control_pump", args={"action": "on", "duration": 300},
                         trace_id="t1", caller="c", required_level="write")
    result: dict = {}

    def wait():
        result.update(broker.wait(req))

    t = threading.Thread(target=wait)
    t.start()
    time.sleep(0.1)
    broker.decide(req.id, "approved", decided_by="test")
    t.join(timeout=3)
    assert result["decision"] == "approved"
    assert result["state"] == "approved"


def test_modify_carries_override_args():
    broker = ApprovalBroker(tools={"control_pump"}, timeout=2, bus=EventBus())
    req = broker.request(tool="control_pump", args={"action": "on", "duration": 300},
                         trace_id="t2", caller="c", required_level="write")
    broker.decide(req.id, "modify", override_args={"action": "on", "duration": 60})
    assert broker.wait(req, timeout=1)["override_args"]["duration"] == 60


def test_reject_and_timeout():
    broker = ApprovalBroker(tools={"control_pump"}, timeout=2, bus=EventBus())
    req = broker.request(tool="control_pump", args={"action": "on"},
                         trace_id="t3", caller="c", required_level="write")
    broker.decide(req.id, "rejected")
    assert broker.wait(req, timeout=1)["decision"] == "rejected"

    broker2 = ApprovalBroker(tools={"control_pump"}, timeout=0.05, bus=EventBus())
    req2 = broker2.request(tool="control_pump", args={"action": "on"},
                           trace_id="t4", caller="c", required_level="write")
    assert broker2.wait(req2)["decision"] == "timeout"


def test_decision_is_idempotent():
    broker = ApprovalBroker(tools={"control_pump"}, timeout=1, bus=EventBus())
    req = broker.request(tool="control_pump", args={"action": "on"},
                         trace_id="t5", caller="c", required_level="write")
    broker.decide(req.id, "approved")
    again = broker.decide(req.id, "rejected")
    assert again["decision"] == "approved"


def test_approval_writes_audit_hash_chain():
    store = AuditStore(chain=True)
    audit = AuditLogger(store)
    broker = ApprovalBroker(tools={"control_pump"}, timeout=2, bus=EventBus(),
                            audit=audit)
    req = broker.request(tool="control_pump", args={"action": "on", "duration": 60},
                         trace_id="t6", caller="spa", required_level="write")
    broker.decide(req.id, "approved", decided_by="tester")
    broker.wait(req, timeout=1)
    records = [r for r in store._ring if r.get("tool") == "hitl.approval"]
    assert records and records[0]["guard_result"] == "passed"
    assert records[0]["rec_hash"]
    ok, _, msg = verify_chain(store._ring)
    assert ok is True, msg


def test_pending_list():
    broker = ApprovalBroker(tools={"control_pump"}, timeout=1, bus=EventBus())
    req = broker.request(tool="control_pump", args={"action": "on"},
                         trace_id="t7", caller="c", required_level="write")
    assert broker.pending()[0]["approval_id"] == req.id
    broker.decide(req.id, "rejected")
    assert broker.pending() == []
