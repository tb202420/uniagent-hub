"""工作流引擎（阶段 3 核心）：JSON 蓝图 → 拓扑排序 → 数据管道 → 条件分支 → 执行。

设计（答辩要点）：
- 智能（Agent 一次性生成蓝图）与执行（引擎按图执行）解耦，Agent 只消耗一次调用 token
- 每步调用仍走 gateway.call()（Guard 校验 + 审计完整，不旁路安全）
- 条件表达式用自研安全解析器（core/workflow/expr.py），零 eval
- 递归防护：步骤中不允许调用 run_workflow 自身；DAG 最长路径深度上限 20（v2.0）
- 并行分支（v2.0）：蓝图声明 `parallel: true` 时按拓扑层并发执行（默认串行，口径不变）
- 事件流（v2.0 初版）：每步状态变化写入内存事件队列，供 /workflows/events 轮询（SPA 进度卡片）
- 单步失败 → 下游标记 skipped，返回部分结果
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from typing import Any

from core.workflow.expr import ExprError, safe_eval

_REF_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")
MAX_DAG_DEPTH = 20          # v2.0：DAG 最长路径深度上限（递归防护）
PARALLEL_MAX_WORKERS = 4    # 并行分支线程池上限（低配友好）


class WorkflowError(ValueError):
    pass


class WorkflowEngine:
    def __init__(self, gateway: Any, max_step_calls_per_tool: int = 5,
                 step_timeout: float = 15.0, workflow_timeout: float = 60.0) -> None:
        self.gateway = gateway          # 复用 Gateway（含 Guard + 审计）
        self.workflows: dict[str, dict] = {}
        self.max_step_calls_per_tool = max_step_calls_per_tool
        self.step_timeout = step_timeout
        self.workflow_timeout = workflow_timeout
        self._wf_calls: list[dict] = []  # 最近执行记录（供 Web 界面可视化）
        # v2.0 事件流：步骤状态事件（进度卡片数据源，/workflows/events 轮询）
        self._events: deque[dict] = deque(maxlen=500)
        self._event_seq = 0
        self._event_lock = threading.Lock()

    # ---- 事件流 ----

    def _emit(self, wf: str, kind: str, **kw) -> None:
        """wf=工作流级 trace_id；kw 可含步骤自身的 trace_id（不冲突）。"""
        with self._event_lock:
            self._event_seq += 1
            self._events.append({"seq": self._event_seq, "wf": wf,
                                 "kind": kind, "ts": round(time.time(), 3), **kw})

    def events(self, since: int = 0, limit: int = 100) -> list[dict]:
        """返回 seq > since 的事件（增量轮询）。"""
        with self._event_lock:
            return [dict(e) for e in self._events
                    if e["seq"] > since][-limit:]

    # ---- 注册 ----

    def register_workflows(self, workflows: dict[str, dict]) -> None:
        for name, bp in workflows.items():
            self._validate_blueprint(name, bp)
        self.workflows.update(workflows)

    def tool_definition(self) -> dict[str, Any]:
        names = sorted(self.workflows.keys())
        return {
            "name": "run_workflow",
            "title": "运行工作流",
            "description": "一次调用执行预定义的多工具工作流（拓扑排序 + 数据管道 + 条件分支）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workflow": {"type": "string", "enum": names},
                    "params": {"type": "object"},
                },
                "required": ["workflow"],
            },
            "annotations": {"readOnlyHint": False},
        }

    # ---- 校验 ----

    def _validate_blueprint(self, name: str, bp: dict) -> None:
        steps = bp.get("steps") or []
        if not steps:
            raise WorkflowError(f"工作流 {name}: steps 为空")
        ids = [s.get("id") for s in steps]
        if len(ids) != len(set(ids)):
            raise WorkflowError(f"工作流 {name}: 步骤 id 重复")
        idset = set(ids)
        for s in steps:
            tool = s.get("tool", "")
            if tool == "run_workflow":
                raise WorkflowError(f"工作流 {name}: 步骤 {s.get('id')} 调用 run_workflow（递归禁止）")
            for dep in (s.get("depends_on") or []):
                if dep not in idset:
                    raise WorkflowError(f"工作流 {name}: 依赖不存在的步骤 {dep}")
        # 注册期即检测循环依赖（fail fast）+ DAG 深度上限（v2.0 递归防护）
        self._topo_order(bp)
        depth = self._dag_depth(bp)
        if depth > MAX_DAG_DEPTH:
            raise WorkflowError(
                f"工作流 {name}: DAG 最长路径深度 {depth} 超过上限 {MAX_DAG_DEPTH}")

    @staticmethod
    def _dag_depth(bp: dict) -> int:
        """最长依赖路径的层数（单步为 1）。"""
        steps = {s["id"]: s for s in bp["steps"]}
        memo: dict[str, int] = {}

        def d(sid: str, seen: frozenset = frozenset()) -> int:
            if sid in memo:
                return memo[sid]
            if sid in seen:      # 循环由 _topo_order 兜底，这里防重入
                return 0
            deps = steps[sid].get("depends_on") or []
            memo[sid] = 1 + max((d(x, seen | {sid}) for x in deps), default=0)
            return memo[sid]

        return max((d(s) for s in steps), default=0)

    # ---- 拓扑排序（Kahn）----

    def _topo_order(self, bp: dict) -> list[dict]:
        steps = {s["id"]: s for s in bp["steps"]}
        indeg = {s["id"]: 0 for s in bp["steps"]}
        adj: dict[str, list[str]] = {s["id"]: [] for s in bp["steps"]}
        for s in bp["steps"]:
            for dep in (s.get("depends_on") or []):
                adj[dep].append(s["id"])
                indeg[s["id"]] += 1
        queue = [i for i, d in indeg.items() if d == 0]
        order: list[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for m in adj[node]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
        if len(order) != len(steps):
            raise WorkflowError("工作流存在循环依赖（无法拓扑排序）")
        return [steps[i] for i in order]

    # ---- 引用解析 ----

    def _resolve_ref(self, ref: str, outputs: dict[str, Any], params: dict[str, Any]) -> Any:
        parts = ref.split(".")
        if parts[0] == "params":
            value: Any = params
            for p in parts[1:]:
                if not isinstance(value, dict) or p not in value:
                    raise WorkflowError(f"引用 {ref} 不存在")
                value = value[p]
            return value
        if len(parts) >= 2 and parts[1] == "output":
            value = outputs.get(parts[0])
            for p in parts[2:]:
                if isinstance(value, dict) and p in value:
                    value = value[p]
                elif isinstance(value, (list, tuple)) and p.isdigit():
                    value = value[int(p)]
                else:
                    raise WorkflowError(f"引用 {ref} 无法解析（步骤 {parts[0]} 输出中无 {p}）")
            return value
        raise WorkflowError(f"引用格式错误: {ref}（支持 {{step.output[.字段]}} / {{params.xxx}}）")

    def _substitute(self, text: str, outputs: dict[str, Any], params: dict[str, Any]) -> Any:
        """替换 {{ref}} 后尝试安全求值（支持算术/条件），否则返回字符串。"""
        def _rep(m: re.Match) -> str:
            value = self._resolve_ref(m.group(1).strip(), outputs, params)
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return repr(value)
        substituted = _REF_RE.sub(_rep, text)
        if _REF_RE.search(substituted):
            raise WorkflowError(f"无法解析的引用: {text}")
        try:
            value = safe_eval(substituted)
            # 整值浮点规整（如 "29.0 - 2" -> 27.0 -> 27），避免整数 Schema 误判
            if isinstance(value, float) and value.is_integer():
                return int(value)
            return value
        except ExprError:
            # 纯字符串（无表达式）→ 还原 repr 转义
            return _unrepr(substituted)

    # ---- 执行 ----

    def run(self, name: str, params: dict[str, Any] | None = None,
            caller: str = "workflow", trace_id: str | None = None,
            permission_level: str = "write") -> dict[str, Any]:
        bp = self.workflows.get(name)
        if bp is None:
            raise WorkflowError(f"工作流不存在: {name}")
        params = params or {}
        trace_id = trace_id or uuid.uuid4().hex[:8]
        wf_start = time.time()
        self._emit(trace_id, "workflow", workflow=name, status="running")

        if bp.get("parallel"):
            return self._run_parallel(bp, name, params, trace_id, wf_start)

        steps = self._topo_order(bp)
        outputs: dict[str, Any] = {}
        results: dict[str, dict[str, Any]] = {}
        tool_calls: dict[str, int] = {}
        ok_all = True

        def _status(sid: str) -> str:
            return results.get(sid, {}).get("status", "pending")

        def _record(r: dict) -> None:
            results[r["id"]] = r
            self._emit(trace_id, "step", **r)

        for step in steps:
            sid = step["id"]
            tool = step["tool"]

            if time.time() - wf_start > self.workflow_timeout:
                ok_all = False
                _record({"id": sid, "tool": tool, "status": "skipped",
                         "error": "工作流整体超时"})
                continue

            # 失败传播：依赖步骤存在 error/skipped → 本步骤跳过
            deps = step.get("depends_on") or []
            if any(_status(d) in ("error", "skipped") for d in deps):
                _record({"id": sid, "tool": tool, "status": "skipped",
                         "error": f"依赖步骤未成功: {[d for d in deps if _status(d) in ('error','skipped')]}"})
                continue

            # 单工具调用次数上限（防循环失控）
            if tool in tool_calls and tool_calls[tool] >= self.max_step_calls_per_tool:
                ok_all = False
                _record({"id": sid, "tool": tool, "status": "skipped",
                         "error": f"单工作流内 {tool} 调用超过上限 {self.max_step_calls_per_tool}"})
                continue
            tool_calls[tool] = tool_calls.get(tool, 0) + 1

            # 条件分支
            cond = step.get("condition")
            if cond:
                try:
                    if not self._substitute(cond, outputs, params):
                        _record({"id": sid, "tool": tool, "status": "skipped",
                                 "error": "条件不满足"})
                        continue
                except WorkflowError as e:
                    ok_all = False
                    _record({"id": sid, "tool": tool, "status": "error",
                             "error": f"条件解析失败: {e}"})
                    continue

            # 参数模板：仅含 {{...}} 的字符串做替换，其余值原样传递（bool/数字/字典不误转换）
            raw_args = step.get("args", {})
            try:
                resolved_args = {}
                for k, v in raw_args.items():
                    if isinstance(v, str) and "{{" in v:
                        resolved_args[k] = self._substitute(v, outputs, params)
                    elif isinstance(v, str):
                        resolved_args[k] = v
                    else:
                        resolved_args[k] = v
            except WorkflowError as e:
                ok_all = False
                _record({"id": sid, "tool": tool, "status": "error",
                         "error": f"参数解析失败: {e}"})
                continue

            # 执行（走 Gateway Guard + 审计；rate_scope 隔离工作流内限流桶）
            step_trace = uuid.uuid4().hex[:8]
            try:
                # internal=True：进程内受信任路径，鉴权模式下 GateWay 采信
                # 引擎传入的 caller/permission_level/rate_scope（BE-3）
                resp = self.gateway.call({
                    "name": tool, "arguments": resolved_args,
                    "caller": caller, "trace_id": step_trace,
                    "permission_level": permission_level,
                    "rate_scope": f"wf:{trace_id}",
                }, internal=True)
            except Exception as e:
                ok_all = False
                _record({"id": sid, "tool": tool, "status": "error",
                         "error": f"执行异常: {e}"})
                continue

            if resp.get("isError"):
                ok_all = False
                _record({"id": sid, "tool": tool, "status": "error",
                         "error": resp["content"][0]["text"][:200]})
                continue

            # 输出提取：文本 → 尝试 JSON 解析（数据管道用）
            text = resp["content"][0]["text"]
            try:
                value: Any = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                value = text
            outputs[sid] = value
            latency = resp.get("meta", {}).get("latency_ms", 0)
            _record({"id": sid, "tool": tool, "status": "ok",
                     "output": value, "latency_ms": latency,
                     "trace_id": step_trace})

        summary = {
            "workflow": name,
            "ok": ok_all,
            "steps": [results[sid] for sid in [s["id"] for s in bp["steps"]]],
            "params": params,
            "trace_id": trace_id,
        }
        self._finish_summary(summary)
        return summary

    def _finish_summary(self, summary: dict) -> None:
        self._wf_calls.append(summary)
        if len(self._wf_calls) > 50:
            self._wf_calls.pop(0)
        self._emit(summary["trace_id"], "workflow", workflow=summary["workflow"],
                   status="ok" if summary["ok"] else "error")

    # ---- 并行分支（v2.0）：按拓扑层并发，层内无依赖可同时执行 ----

    def _topo_layers(self, bp: dict) -> list[list[dict]]:
        steps = {s["id"]: s for s in bp["steps"]}
        indeg = {s["id"]: len(s.get("depends_on") or []) for s in bp["steps"]}
        ready = [i for i, d in indeg.items() if d == 0]
        layers: list[list[dict]] = []
        while ready:
            layers.append([steps[i] for i in ready])
            nxt: list[str] = []
            for i in ready:
                for s in bp["steps"]:
                    if i in (s.get("depends_on") or []):
                        indeg[s["id"]] -= 1
                        if indeg[s["id"]] == 0:
                            nxt.append(s["id"])
            ready = nxt
        if sum(len(l) for l in layers) != len(steps):
            raise WorkflowError("工作流存在循环依赖（无法拓扑分层）")
        return layers

    def _run_parallel(self, bp: dict, name: str, params: dict,
                      trace_id: str, wf_start: float) -> dict[str, Any]:
        outputs: dict[str, Any] = {}
        results: dict[str, dict[str, Any]] = {}
        lock = threading.Lock()
        ok_all = True

        def _record(r: dict) -> None:
            with lock:
                results[r["id"]] = r
            self._emit(trace_id, "step", **r)

        def _status(sid: str) -> str:
            with lock:
                return results.get(sid, {}).get("status", "pending")

        def _exec(step: dict) -> None:
            nonlocal ok_all
            sid, tool = step["id"], step["tool"]
            if time.time() - wf_start > self.workflow_timeout:
                ok_all = False
                return _record({"id": sid, "tool": tool, "status": "skipped",
                                "error": "工作流整体超时"})
            deps = step.get("depends_on") or []
            bad = [d for d in deps if _status(d) in ("error", "skipped")]
            if bad:
                return _record({"id": sid, "tool": tool, "status": "skipped",
                                "error": f"依赖步骤未成功: {bad}"})
            cond = step.get("condition")
            if cond:
                try:
                    with lock:
                        if not self._substitute(cond, outputs, params):
                            return _record({"id": sid, "tool": tool,
                                            "status": "skipped", "error": "条件不满足"})
                except WorkflowError as e:
                    ok_all = False
                    return _record({"id": sid, "tool": tool, "status": "error",
                                    "error": f"条件解析失败: {e}"})
            with lock:
                try:
                    resolved = {k: (self._substitute(v, outputs, params)
                                    if isinstance(v, str) and "{{" in v else v)
                                for k, v in step.get("args", {}).items()}
                except WorkflowError as e:
                    ok_all = False
                    return _record({"id": sid, "tool": tool, "status": "error",
                                    "error": f"参数解析失败: {e}"})
            step_trace = uuid.uuid4().hex[:8]
            try:
                resp = self.gateway.call({
                    "name": tool, "arguments": resolved,
                    "caller": "workflow", "trace_id": step_trace,
                    "permission_level": "write",
                    "rate_scope": f"wf:{trace_id}",
                }, internal=True)
            except Exception as e:  # noqa: BLE001
                ok_all = False
                return _record({"id": sid, "tool": tool, "status": "error",
                                "error": f"执行异常: {e}"})
            if resp.get("isError"):
                ok_all = False
                return _record({"id": sid, "tool": tool, "status": "error",
                                "error": resp["content"][0]["text"][:200]})
            text = resp["content"][0]["text"]
            try:
                value = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                value = text
            with lock:
                outputs[sid] = value
            _record({"id": sid, "tool": tool, "status": "ok", "output": value,
                     "latency_ms": resp.get("meta", {}).get("latency_ms", 0),
                     "trace_id": step_trace})

        for layer in self._topo_layers(bp):
            with ThreadPoolExecutor(max_workers=PARALLEL_MAX_WORKERS) as pool:
                list(pool.map(_exec, layer))

        summary = {
            "workflow": name,
            "ok": ok_all,
            "steps": [results[s["id"]] for s in bp["steps"]],
            "params": params,
            "trace_id": trace_id,
            "parallel": True,
        }
        self._finish_summary(summary)
        return summary

    def recent(self, limit: int = 10) -> list[dict]:
        return list(reversed(self._wf_calls[-limit:]))


def _unrepr(s: str) -> Any:
    """把 repr 化的结果还原为原始值（数字/字符串）。"""
    try:
        return safe_eval(s)
    except ExprError:
        return s
