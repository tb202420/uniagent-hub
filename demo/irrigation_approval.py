"""演示闭环一键脚本（v3.0 第一阶段）。

链路：场景（智能灌溉）→ Agent 计划 → 读土壤湿度 → 写工具 control_pump
     → Guard HITL 审批（暂停等待）→ 批准 → MQTT 命令 → 温室节点动作。

不依赖手动点击：脚本自己起本地 MQTT Broker + 温室模拟器 + Hub，
并作为"审批人"在事件流里看到 hitl.request 后自动决策（可改 --manual）。

诚实标注：
- 默认设备是 **SIL 模拟器**（sim_esp32_greenhouse），不是真机；
  日志与终端都会打印「设备模式：SIL」。
- --real 模式会先等真机上线；超时后才启动模拟器，并打印
  「已切换模拟设备（SIL 兜底）」。

用法：
    .venv\\Scripts\\python.exe -m demo.irrigation_approval
    ... --decision reject        # 演示拒绝分支
    ... --decision modify        # 演示"改成 60 秒"
    ... --manual                 # 不自动审批，留给人点
    ... --real --device-timeout 8
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data" / "demo_runs"
BROKER_PORT = 1884
HUB_PORT = 8021


def _env() -> dict[str, str]:
    env = {**os.environ, "PYTHONUTF8": "1"}
    # 演示是本地回路：显式清掉可能继承的鉴权环境，避免客户端未带 token 被 401
    for key in ("HUB_API_TOKEN", "HUB_AUTH_MODE", "HUB_JWT_SECRET"):
        env.pop(key, None)
    env.update({
        "HUB_DB": str(ROOT / "data" / "demo_irrigation.db"),
        "HUB_AUDIT_FILE": str(ROOT / "data" / "demo_irrigation_audit.jsonl"),
        "HUB_AUDIT_CHAIN": "1",
        "HUB_APPROVAL_TOOLS": "control_pump",
        "HUB_APPROVAL_TIMEOUT": "45",
        "HUB_SELF_URL": f"http://127.0.0.1:{HUB_PORT}",
    })
    return env


def _spawn(cmd: list[str], log_path: Path, env: dict[str, str]) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=handle,
                            stderr=subprocess.STDOUT, text=True)
    proc._ua_log_handle = handle  # type: ignore[attr-defined]
    return proc


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    handle = getattr(proc, "_ua_log_handle", None)
    if handle:
        handle.close()


def _wait_port(port: int, timeout: float = 15.0, host: str = "127.0.0.1") -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _tools(base: str) -> list[str]:
    try:
        resp = httpx.post(f"{base}/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            timeout=5)
        return [t["name"] for t in resp.json().get("result", {}).get("tools", [])]
    except Exception:
        return []


def _device_ready(base: str) -> bool:
    """以真实读取探针判断设备是否可调用（避免 SQLite 恢复的旧注册造成假就绪）。"""
    try:
        resp = httpx.post(f"{base}/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "get_soil_moisture", "arguments": {},
                       "caller": "demo-probe", "permission_level": "read"}},
            timeout=5)
        return not resp.json().get("result", {}).get("isError", True)
    except Exception:
        return False


def _wait_device(base: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if "control_pump" in _tools(base) and _device_ready(base):
            return True
        time.sleep(0.5)
    return False


def _approver(base: str, auto: bool, decision: str, delay: float,
              events: list[dict], stop: threading.Event,
              result: dict) -> None:
    """WS 订阅者 + 审批人（独立线程）。"""
    from websockets.sync.client import connect

    token = httpx.post(f"{base}/events/token", timeout=5).json()["token"]
    proto = f"ua.events.{token}"
    url = base.replace("http://", "ws://") + "/ws/events"
    started = time.time()
    try:
        with connect(url, subprotocols=[proto], open_timeout=5) as ws:
            while not stop.is_set() and time.time() - started < 60:
                try:
                    raw = ws.recv(timeout=0.2)
                except TimeoutError:
                    continue
                event = json.loads(raw)
                events.append(event)
                if event.get("kind") == "hitl.request":
                    approval = event["approval"]
                    result["approval"] = approval
                    print(f"[approver] 收到审批请求：{approval['summary']}")
                    if auto:
                        time.sleep(delay)
                        resp = httpx.post(f"{base}/hitl/decide", json={
                            "approval_id": approval["approval_id"],
                            "decision": decision,
                            "override_args": ({"action": "on", "duration": 60}
                                              if decision == "modify" else None),
                            "decided_by": "demo-script"}, timeout=5)
                        result["decision_resp"] = resp.json()
                        print(f"[approver] 已提交决策：{decision}")
                elif event.get("kind") == "hitl.decision":
                    result["decision"] = event["approval"]
                elif event.get("kind") == "tool.stage":
                    print(f"[{event['stage']}] {event['tool']} "
                          f"{event.get('latency_ms', '')}ms")
    except Exception as e:  # noqa: BLE001
        print(f"[approver] 事件流结束：{type(e).__name__}: {e}")


def run(args: argparse.Namespace) -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = RUN_DIR / f"irrigation_approval_{stamp}.log"
    jsonl_path = RUN_DIR / f"irrigation_approval_{stamp}.jsonl"
    pids_path = RUN_DIR / f"irrigation_approval_{stamp}.pids"

    base = f"http://127.0.0.1:{HUB_PORT}"
    env = _env()
    procs: list[subprocess.Popen] = []
    events: list[dict] = []
    device_mode = "SIL（模拟器）"
    timings: dict[str, float] = {}
    ok = False
    stop = threading.Event()
    decision_result: dict = {}

    try:
        print("=" * 64)
        print("UniAgent Hub 演示闭环：智能灌溉 + HITL 审批")
        print("=" * 64)

        broker = _spawn([sys.executable, "-m", "scripts.dev_mqtt_broker",
                         "--port", str(BROKER_PORT)],
                        RUN_DIR / f"broker_{stamp}.log", env)
        procs.append(broker)
        if not _wait_port(BROKER_PORT):
            print("[demo] 本地 Broker 启动失败")
            return 1
        print(f"[demo] 本地 MQTT Broker 就绪（127.0.0.1:{BROKER_PORT}）")

        sim = None
        if not args.real:
            sim = _spawn([sys.executable, "-m",
                          "adapters.mqtt_adapter.sim_esp32_greenhouse",
                          "--broker", f"mqtt://127.0.0.1:{BROKER_PORT}",
                          "--init-soil", "25", "--interval", "5"],
                         RUN_DIR / f"sim_{stamp}.log", env)
            procs.append(sim)
            print("[demo] 设备模式：SIL（模拟器，非真机）")
        else:
            device_mode = "HIL（真机）"
            print(f"[demo] 等待真机上线（{args.device_timeout}s）…")

        hub = _spawn([sys.executable, "-u", "main.py", "--port", str(HUB_PORT),
                      "--broker", f"mqtt://127.0.0.1:{BROKER_PORT}"],
                     RUN_DIR / f"hub_{stamp}.log", env)
        procs.append(hub)
        if not _wait_port(HUB_PORT):
            print("[demo] Hub 启动失败（见日志）")
            return 1

        t0 = time.time()
        if args.real and not _wait_device(base, args.device_timeout):
            print("[demo] 真机未上线 → 已切换模拟设备（SIL 兜底）")
            device_mode = "SIL（真机离线兜底）"
            sim = _spawn([sys.executable, "-m",
                          "adapters.mqtt_adapter.sim_esp32_greenhouse",
                          "--broker", f"mqtt://127.0.0.1:{BROKER_PORT}",
                          "--init-soil", "25", "--interval", "5"],
                         RUN_DIR / f"sim_{stamp}.log", env)
            procs.append(sim)
        if not _wait_device(base):
            print("[demo] 温室节点未注册（control_pump 未出现）")
            return 1
        timings["device_discover"] = round(time.time() - t0, 3)
        print(f"[demo] 温室节点已发现 · {device_mode} · "
              f"{timings['device_discover']}s")

        with pids_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(str(p.pid) for p in procs))

        trace_id = uuid.uuid4().hex[:8]
        worker = threading.Thread(
            target=_approver,
            args=(base, not args.manual, args.decision, args.approval_delay,
                  events, stop, decision_result),
            daemon=True)
        worker.start()
        time.sleep(0.5)

        goal = args.goal
        t1 = time.time()
        resp = httpx.post(f"{base}/agent/run", json={
            "agent": "script", "goal": goal, "permission": "write",
            "trace_id": trace_id}, timeout=130)
        out = resp.json()
        if resp.status_code != 200:
            print(f"[demo] Agent 执行入口失败: HTTP {resp.status_code} {out}")
            return 1
        app_trace = out.get("trace_id", trace_id)
        timings["workflow"] = round(time.time() - t1, 3)
        agent_ok = bool(out.get("ok"))
        print(f"[demo] Agent 结果: ok={agent_ok} · {out.get('summary', '')[:120]}")
        print(f"[demo] 工作流耗时 {timings['workflow']}s · trace={app_trace}")

        if decision_result.get("approval"):
            created = decision_result["approval"].get("created_ts", 0)
            decided = (decision_result.get("decision") or {}).get("decided_ts")
            if created and decided:
                timings["approval_wait"] = round(decided - created, 3)
                print(f"[demo] 审批等待 {timings['approval_wait']}s")

        # 采集收尾：给最后一个 span.end 事件留出到达时间（避免统计口径少一条）
        time.sleep(0.3)
        stop.set()
        worker.join(timeout=2)

        # 审计哈希链校验（审批决策必须已在链上）
        from core.guard.audit import read_jsonl, verify_chain
        audit_path = Path(env["HUB_AUDIT_FILE"])
        audits = read_jsonl(audit_path) if audit_path.exists() else []
        chain_ok, _, chain_msg = verify_chain(audits)
        approval_rows = [r for r in audits if r.get("tool") == "hitl.approval"]
        cp_rows = [r for r in audits if r.get("tool") == "control_pump"]
        cp_last = cp_rows[-1] if cp_rows else None

        # 分支判定：不是"只要退出码 0 就算成功"，而是检查该分支应有的结果
        if args.decision == "rejected":
            branch_ok = (not agent_ok and cp_last is not None
                         and cp_last.get("guard_result") == "blocked"
                         and cp_last.get("error_code") == 1003)
        elif args.decision == "modify":
            branch_ok = (agent_ok and cp_last is not None
                         and int(cp_last.get("args", {}).get("duration", 0)) == 60)
        else:
            branch_ok = (agent_ok and cp_last is not None
                         and cp_last.get("guard_result") == "passed")
        cp_view = ({"guard_result": cp_last.get("guard_result"),
                    "error_code": cp_last.get("error_code"),
                    "args": cp_last.get("args")} if cp_last else None)
        print(f"[demo] 分支判定: decision={args.decision} branch_ok={branch_ok}")
        print(f"[demo] control_pump 审计: {json.dumps(cp_view, ensure_ascii=False)}")
        print(f"[demo] 审计链: {chain_msg} · 审批记录 {len(approval_rows)} 条")

        summary = {
            "stamp": stamp, "goal": goal, "trace_id": trace_id,
            "branch": args.decision, "ok": branch_ok, "agent_ok": agent_ok,
            "device_mode": device_mode, "timings": timings,
            "approval": decision_result.get("approval"),
            "decision": decision_result.get("decision"),
            "control_pump_audit": cp_view,
            "audit_chain_ok": chain_ok, "audit_chain_msg": chain_msg,
            "event_count": len(events),
        }
        with jsonl_path.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            f.write(json.dumps({"kind": "demo.summary", **summary},
                               ensure_ascii=False) + "\n")
        log_path.write_text(
            "\n".join([
                f"演示闭环 {stamp}",
                f"目标: {goal}",
                f"分支: {args.decision}（branch_ok={branch_ok}）",
                f"设备模式: {device_mode}（非真机数字请勿冒充 HIL）",
                f"Agent 结果: ok={agent_ok}",
                f"耗时: {json.dumps(timings, ensure_ascii=False)}",
                f"control_pump 审计: {json.dumps(cp_view, ensure_ascii=False)}",
                f"审批: {json.dumps(decision_result.get('decision'), ensure_ascii=False)}",
                f"审计链: {chain_msg}",
                f"事件数: {len(events)}",
            ]), encoding="utf-8")
        print(f"[demo] 日志已写入 {log_path.relative_to(ROOT)}")
        print(f"[demo] 事件已写入 {jsonl_path.relative_to(ROOT)}")
        return 0 if branch_ok and chain_ok else 1

    finally:
        stop.set()
        for proc in reversed(procs):
            _stop(proc)


def main() -> int:
    parser = argparse.ArgumentParser(description="智能灌溉 + HITL 审批闭环演示")
    parser.add_argument("--goal", default="土壤干了，帮我浇水 300 秒")
    parser.add_argument("--decision", choices=("approved", "rejected", "modify"),
                        default="approved")
    parser.add_argument("--approval-delay", type=float, default=2.0,
                        help="自动审批前的停留秒数（让界面能看到等待态）")
    parser.add_argument("--manual", action="store_true",
                        help="不自动审批，留给人在 SPA 里点")
    parser.add_argument("--real", action="store_true",
                        help="先等真机；超时自动切换模拟器（SIL 兜底）")
    parser.add_argument("--device-timeout", type=float, default=8.0)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

