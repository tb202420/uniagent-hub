"""A2A 最小端点服务测试（v3.0 批次，克制实现边界）。"""

import time

import pytest

from core.a2a.service import A2AService
from core.gateway.event_bus import EventBus


class _FakeGateway:
    def __init__(self):
        self.calls: list[dict] = []

    def call(self, params, internal=False):
        self.calls.append({**params, "internal": internal})
        return {"isError": False,
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "meta": {"latency_ms": 1}}


def _wait(service: A2AService, task_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = service.get(task_id)
        if task and task["status"] in ("completed", "failed"):
            return task
        time.sleep(0.03)
    raise AssertionError("A2A 任务未结束")


def test_submit_requires_goal():
    service = A2AService(_FakeGateway(), bus=EventBus())
    with pytest.raises(ValueError):
        service.submit({"goal": "  "})


def test_submit_rejects_bad_permission():
    service = A2AService(_FakeGateway(), bus=EventBus())
    with pytest.raises(ValueError, match="permission"):
        service.submit({"goal": "巡检", "permission": "root"})


def test_workflow_task_completes_with_write():
    gw = _FakeGateway()
    service = A2AService(gw, bus=EventBus())
    task = service.submit({"goal": "帮我巡检一下环境", "permission": "write"})
    assert task["status"] in ("submitted", "working", "completed")
    done = _wait(service, task["task_id"])
    assert done["status"] == "completed"
    assert gw.calls[0]["name"] == "run_workflow"
    assert gw.calls[0]["permission_level"] == "write"


def test_workflow_task_denied_without_write():
    gw = _FakeGateway()
    service = A2AService(gw, bus=EventBus())
    task = service.submit({"goal": "帮我浇水 300 秒", "permission": "read"})
    done = _wait(service, task["task_id"])
    assert done["status"] == "failed"
    assert "write" in done["error"]
    assert gw.calls == []


def test_read_only_discovery_task_completes():
    gw = _FakeGateway()
    service = A2AService(gw, bus=EventBus())
    task = service.submit({"goal": "看看有什么工具", "permission": "read"})
    done = _wait(service, task["task_id"])
    assert done["status"] == "completed"
    assert [c["name"] for c in gw.calls] == ["discover_tools", "get_tool_schema"]


def test_get_unknown_and_list():
    service = A2AService(_FakeGateway(), bus=EventBus())
    assert service.get("nope") is None
    task = service.submit({"goal": "看看有什么工具", "permission": "read"})
    _wait(service, task["task_id"])
    assert service.list()[0]["task_id"] == task["task_id"]


def test_agents_listing_default():
    service = A2AService(_FakeGateway(), bus=EventBus())
    assert service.agents() == ["script"]
