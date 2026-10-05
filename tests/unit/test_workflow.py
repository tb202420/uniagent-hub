"""WorkflowEngine 单元测试（fake gateway）。"""

import pytest

from core.workflow.engine import WorkflowEngine, WorkflowError
from core.workflow.expr import ExprError

BP = {
    "office_cooling": {
        "steps": [
            {"id": "s1", "tool": "get_temperature", "args": {}},
            {"id": "s2", "tool": "get_weather", "args": {"latitude": 1.0, "longitude": 2.0},
             "depends_on": ["s1"]},
            {"id": "s3", "tool": "ac_control",
             "args": {"action": "on", "temperature": "{{s1.output}} - 2"},
             "depends_on": ["s1"], "condition": "{{s1.output}} > 28"},
        ]
    },
    "status": {
        "steps": [
            {"id": "s1", "tool": "file_summary", "args": {"directory": "{{params.dir}}",
                                                          "ext": "{{params.ext}}"}},
        ]
    },
}


class FakeGateway:
    """模拟 Gateway.call：get_temperature 返回 29.5；其余成功。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call(self, params: dict, **kwargs) -> dict:
        # kwargs 兼容网关新增的 internal/authenticated 参数（BE-1/BE-3）
        self.calls.append(params)
        name = params["name"]
        if name == "get_temperature":
            return {"content": [{"type": "text", "text": "29.5"}], "isError": False,
                    "meta": {"latency_ms": 1}}
        if name == "get_weather":
            return {"content": [{"type": "text", "text": '{"temp": 33}'}],
                    "isError": False, "meta": {"latency_ms": 2}}
        if name == "file_summary":
            return {"content": [{"type": "text", "text": '{"count": 3}'}],
                    "isError": False, "meta": {"latency_ms": 1}}
        if name == "fail_tool":
            return {"content": [{"type": "text", "text": "[error 1006] boom"}],
                    "isError": True, "meta": {"error_code": 1006}}
        return {"content": [{"type": "text", "text": "ok"}], "isError": False,
                "meta": {"latency_ms": 1}}


def _engine() -> WorkflowEngine:
    e = WorkflowEngine(FakeGateway())
    e.register_workflows(BP)
    return e


def test_condition_true_triggers_step3():
    e = _engine()
    summary = e.run("office_cooling", params={})
    statuses = {s["id"]: s["status"] for s in summary["steps"]}
    assert statuses == {"s1": "ok", "s2": "ok", "s3": "ok"}
    s3 = next(s for s in summary["steps"] if s["id"] == "s3")
    assert s3["output"] == "ok"
    # 数据管道：29.5 - 2 = 27.5 → 传给 ac_control
    ac_call = next(c for c in e.gateway.calls if c["name"] == "ac_control")
    assert ac_call["arguments"]["temperature"] == 27.5


def test_condition_false_skips_step3():
    e = _engine()

    class HotGateway(FakeGateway):
        def call(self, params):
            if params["name"] == "get_temperature":
                return {"content": [{"type": "text", "text": "24.0"}],
                        "isError": False, "meta": {"latency_ms": 1}}
            return super().call(params)

    e.gateway = HotGateway()
    summary = e.run("office_cooling")
    statuses = {s["id"]: s["status"] for s in summary["steps"]}
    assert statuses["s3"] == "skipped"
    assert not any(c["name"] == "ac_control" for c in e.gateway.calls)


def test_params_pipeline():
    e = _engine()
    summary = e.run("status", params={"dir": "/tmp", "ext": "py"})
    call = next(c for c in e.gateway.calls if c["name"] == "file_summary")
    assert call["arguments"] == {"directory": "/tmp", "ext": "py"}
    assert summary["ok"] is True


def test_step_failure_marks_error():
    e = WorkflowEngine(FakeGateway())
    e.register_workflows({"wf": {"steps": [
        {"id": "s1", "tool": "fail_tool", "args": {}},
        {"id": "s2", "tool": "get_weather", "args": {}, "depends_on": ["s1"]},
    ]}})
    summary = e.run("wf")
    statuses = {s["id"]: s["status"] for s in summary["steps"]}
    assert statuses["s1"] == "error"
    assert summary["ok"] is False


def test_cycle_detected():
    e = WorkflowEngine(FakeGateway())
    with pytest.raises(WorkflowError, match="循环依赖"):
        e.register_workflows({"cyc": {"steps": [
            {"id": "a", "tool": "x", "args": {}, "depends_on": ["b"]},
            {"id": "b", "tool": "y", "args": {}, "depends_on": ["a"]},
        ]}})


def test_recursion_blocked():
    e = WorkflowEngine(FakeGateway())
    with pytest.raises(WorkflowError, match="递归"):
        e.register_workflows({"bad": {"steps": [
            {"id": "s1", "tool": "run_workflow", "args": {}},
        ]}})


def test_unknown_workflow():
    e = _engine()
    with pytest.raises(WorkflowError, match="不存在"):
        e.run("nope")


def test_call_cap_enforced():
    e = WorkflowEngine(FakeGateway(), max_step_calls_per_tool=2)
    e.register_workflows({"loop": {"steps": [
        {"id": f"s{i}", "tool": "get_weather", "args": {}} for i in range(5)
    ]}})
    summary = e.run("loop")
    statuses = [s["status"] for s in summary["steps"]]
    assert statuses.count("ok") == 2
    assert any(s == "skipped" for s in statuses)
