"""A2A 最小端点（v3.0，克制实现）。

范围（明确边界，不扩展）：
- `POST /a2a/tasks`：任务委派，立即返回 task_id（202）
- `GET  /a2a/tasks/{id}`：状态查询（submitted / working / completed / failed）
- 不做完整 A2A 生命周期、不做流式事件、不做多轮协商（冻结原则）

执行路径：委派给进程内 Agent 插件（默认 script 确定性插件），工具调用仍走
Gateway 的 Guard 管道与审计，不旁路安全。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any

from core.gateway.event_bus import EventBus, default_bus

SUBMITTED = "submitted"
WORKING = "working"
COMPLETED = "completed"
FAILED = "failed"


class A2AService:
    def __init__(self, gateway: Any, bus: EventBus | None = None,
                 max_tasks: int = 50, agents_loader: Any | None = None,
                 self_url: str | None = None) -> None:
        self.gateway = gateway
        self.bus = bus or default_bus
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: deque[str] = deque(maxlen=max_tasks)
        self._lock = threading.Lock()
        self._agents_loader = agents_loader
        self.self_url = self_url

    # ---- API ----

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        goal = str(body.get("goal") or "").strip()
        if not goal:
            raise ValueError("goal 不能为空")
        agent = str(body.get("agent") or "script").strip()
        permission = str(body.get("permission") or "read").strip()
        if permission not in ("read", "write", "admin"):
            raise ValueError(f"permission 非法: {permission}")
        task_id = uuid.uuid4().hex[:10]
        task = {"task_id": task_id, "agent": agent, "goal": goal,
                "permission": permission, "status": SUBMITTED,
                "created_ts": round(time.time(), 3), "updated_ts": round(time.time(), 3),
                "result": None, "error": ""}
        with self._lock:
            self._tasks[task_id] = task
            self._order.append(task_id)
            if self._order and len(self._tasks) > self._order.maxlen:
                old = next(iter(self._tasks))
                if old != task_id:
                    self._tasks.pop(old, None)
        self.bus.publish("a2a.task", task=dict(task))
        threading.Thread(target=self._execute, args=(task_id,),
                         daemon=True, name=f"a2a-{task_id}").start()
        return self.get(task_id) or task

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._order)[-limit:]
            return [dict(self._tasks[i]) for i in reversed(ids)
                    if i in self._tasks]

    def agents(self) -> list[str]:
        if self._agents_loader is None:
            return ["script"]
        try:
            return sorted(self._agents_loader().keys())
        except Exception:  # noqa: BLE001
            return ["script"]

    # ---- 执行（后台线程；不阻塞 HTTP 事件循环）----

    def _execute(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task["status"] = WORKING
            task["updated_ts"] = round(time.time(), 3)
            snapshot = dict(task)
        self.bus.publish("a2a.task", task=snapshot)
        try:
            result = self._dispatch(task)
            status = COMPLETED if result.get("ok") else FAILED
            error = "" if result.get("ok") else str(result.get("summary") or "")[:300]
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "steps": [], "summary": f"{type(e).__name__}: {e}"}
            status, error = FAILED, f"{type(e).__name__}: {e}"[:300]
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.update({"status": status, "result": result,
                             "error": error, "updated_ts": round(time.time(), 3)})
                snapshot = dict(task)
        self.bus.publish("a2a.task", task=snapshot)

    def _dispatch(self, task: dict[str, Any]) -> dict[str, Any]:
        agent = task["agent"]
        goal, permission = task["goal"], task["permission"]
        if agent == "script":
            from agent.plugins.script_agent import ScriptAgent
            plan = ScriptAgent.plan_goal(goal)
            if plan.get("kind") == "workflow":
                if permission not in ("write", "admin"):
                    return {"ok": False, "plan": plan, "steps": [],
                            "summary": "该目标需要 write 权限（A2A 委派未授予）"}
                resp = self.gateway.call({
                    "name": "run_workflow",
                    "arguments": {"workflow": plan["workflow"],
                                  "params": plan.get("params", {})},
                    "caller": f"a2a:{task['task_id']}",
                    "trace_id": task["task_id"],
                    "permission_level": permission,
                }, internal=True)
                ok = not resp.get("isError")
                text = _text(resp)
                return {"ok": ok, "plan": plan,
                        "steps": [{"step": plan["workflow"], "ok": ok,
                                   "output": text[:400]}],
                        "summary": text[:250]}
            # 非工作流目标：经元工具链（只读，安全）
            steps = []
            for name, args in (("discover_tools", {"query": ""}),
                               ("get_tool_schema", {"name": goal[:32]})):
                resp = self.gateway.call({
                    "name": name, "arguments": args,
                    "caller": f"a2a:{task['task_id']}", "trace_id": task["task_id"],
                    "permission_level": permission}, internal=True)
                ok = not resp.get("isError")
                steps.append({"step": name, "ok": ok,
                              "output": _text(resp)[:300]})
                if not ok:
                    return {"ok": False, "plan": plan, "steps": steps,
                            "summary": _text(resp)[:250]}
            return {"ok": True, "plan": plan, "steps": steps,
                    "summary": "A2A 任务完成（只读发现链）"}
        if self._agents_loader is None:
            return {"ok": False, "steps": [],
                    "summary": f"未加载 Agent 插件宿主，无法委派 {agent}"}
        agents = self._agents_loader()
        adapter = agents.get(agent)
        if adapter is None:
            return {"ok": False, "steps": [],
                    "summary": f"Agent 不存在: {agent}（可用: {sorted(agents)}）"}
        return adapter.run(goal, gateway_url=self.self_url or
                           "http://127.0.0.1:8020", permission=permission)


def _text(resp: dict[str, Any]) -> str:
    return (resp.get("content") or [{}])[0].get("text", "")
