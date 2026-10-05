"""演示彩排自动化：按 v1.3 八幕跑完全流程并输出 8 项完整度评分（真实证据来源）。

前置：`scripts/demo_start.ps1` 已启动全栈（P1-P6 就绪）。
本脚本按 docs/demo_script.md v1.3 依次执行，逐项判定 §12 评分表，
把"是否 8/8"变成可复现的机器判定，而不是人工目测。
工具数期望值默认 14（演示档 = 软件档 11 + 温室模拟节点 3），可用 --expect-tools 覆盖。

用法：
    python -m scripts.demo_rehearsal --label "第1次"
退出码：0 = 8/8 通过；1 = 有未通过项。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from agent.demo_agent import MCPClient

HERE = Path(__file__).resolve().parent.parent
_READ = "read"
_WRITE = "write"


def _text(res: dict) -> str:
    return (res.get("content") or [{}])[0].get("text", "")


def _code(res: dict) -> int:
    return (res.get("meta") or {}).get("error_code", 0)


def _latency(res: dict) -> int:
    return (res.get("meta") or {}).get("latency_ms", 0)


def _run_py(args: list[str], timeout: float = 120.0) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, *args], cwd=HERE, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="UniAgent Hub 演示彩排自动化")
    parser.add_argument("--url", default="http://127.0.0.1:8020")
    parser.add_argument("--dashboard", default="http://127.0.0.1:18080")
    parser.add_argument("--label", default="彩排")
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--expect-tools", type=int, default=14,
                        help="期望注册工具数（演示档 14 = 软件档 11 + 温室模拟节点 3）")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    scores: dict[int, tuple[bool, str]] = {}
    errors: list[str] = []
    t0 = time.perf_counter()

    print("=" * 68)
    print(f"UniAgent Hub 演示彩排 — {args.label}（{base}）")
    print("=" * 68)

    # ---------- 评分 1：P1-P6 就绪（重新校验，不信任启动时的结论） ----------
    print("\n[评分1] P1-P6 就绪校验")
    readiness: list[tuple[str, bool, str]] = []
    try:
        hz = httpx.get(f"{base}/healthz", timeout=5).json()
        readiness.append(("Hub /healthz", hz.get("status") == "ok", str(hz)))
    except Exception as e:
        readiness.append(("Hub /healthz", False, f"{type(e).__name__}: {e}"))

    client = MCPClient(base, timeout=60.0)
    tools: list[dict] = []
    try:
        tools = client.list_tools()
    except Exception as e:
        errors.append(f"tools/list 失败: {e}")

    # P4 预热验证：连续两次 get_weather，第二次应命中缓存
    wet_lat = []
    for _ in range(2):
        try:
            r = client.call_tool("get_weather",
                                 {"latitude": 39.9042, "longitude": 116.4074,
                                  "current_weather": True}, caller="rehearsal_ready")
            wet_lat.append(_latency(r) if not r.get("isError") else -1)
        except Exception:
            wet_lat.append(-1)
    ready_p4 = len(wet_lat) == 2 and wet_lat[1] == 0
    readiness.append(("get_weather 预热", ready_p4, f"latencies={wet_lat}"))

    # P2/P3 设备可用
    try:
        r_t = client.call_tool("get_temperature", {}, caller="rehearsal_ready")
        ok_t = not r_t.get("isError")
        r_a = client.call_tool("get_ac_state", {}, caller="rehearsal_ready")
        ok_a = not r_a.get("isError")
        readiness.append(("温度/空调模拟器", ok_t and ok_a,
                          f"temp={_text(r_t) if ok_t else _code(r_t)}, "
                          f"ac={_text(r_a)[:60] if ok_a else _code(r_a)}"))
    except Exception as e:
        readiness.append(("温度/空调模拟器", False, f"{type(e).__name__}: {e}"))

    ok1 = all(x[1] for x in readiness)
    for n, ok, d in readiness:
        print(f"    {'✓' if ok else '✗'} {n}: {d}")
    scores[1] = (ok1, "P1-P6 就绪" + ("" if ok1 else " — " +
                                     ", ".join(n for n, o, _ in readiness if not o)))

    # ---------- 第二幕 + 第三幕（走真实演示命令）----------
    print("\n[第二幕] 统一工具发现（真实命令 agent.llm_agent --script）")
    rc, out = _run_py(["-u", "-m", "agent.llm_agent", "--script", "--url", base])
    print("\n".join("    " + ln for ln in out.strip().splitlines()))
    if rc != 0:
        errors.append(f"llm_agent --script 退出码 {rc}")

    m = re.search(r"工具发现：(\d+) 个工具", out)
    n_tools = int(m.group(1)) if m else len(tools)
    scores[2] = (n_tools == args.expect_tools,
                 f"tools/list 返回 {n_tools} 个工具（期望 {args.expect_tools}）")

    # ---------- 第三幕：单工具三连 ----------
    print("\n[第三幕] 单工具调用")
    act2_detail: list[str] = []
    gt = client.call_tool("get_temperature", {}, caller="rehearsal_act2")
    temp_val = _text(gt) if not gt.get("isError") else ""
    try:
        temp_num = float(temp_val)
    except ValueError:
        temp_num = None
    act2_detail.append(f"get_temperature={temp_val}({_latency(gt)}ms)")
    gs = client.call_tool("git_status", {"repo_path": str(HERE)}, caller="rehearsal_act2")
    act2_detail.append(f"git_status={'ok' if not gs.get('isError') else _code(gs)}"
                       f"({_latency(gs)}ms)")
    gw = client.call_tool("get_weather",
                          {"latitude": 39.9042, "longitude": 116.4074,
                           "current_weather": True}, caller="rehearsal_act2")
    act2_detail.append(f"get_weather={_latency(gw)}ms"
                       f"{'(缓存)' if _latency(gw) == 0 else ''}")
    print("    " + " | ".join(act2_detail))
    ok3 = (temp_num is not None and 28 < temp_num < 35
           and not gs.get("isError") and _latency(gw) == 0)
    scores[3] = (ok3, "；".join(act2_detail))

    # ---------- 第三幕：工作流闭环 ----------
    print("\n[第三幕] 工作流闭环 run_workflow(office_cooling)")
    wf = client.call_tool("run_workflow", {"workflow": "office_cooling"},
                          caller="rehearsal_wf", permission_level=_WRITE)
    wf_text = _text(wf)
    print(f"    {wf_text[:400]}")
    steps: list[dict] = []
    try:
        steps = json.loads(wf_text).get("steps", [])
    except json.JSONDecodeError:
        errors.append("工作流返回非 JSON")
    wf_ok = (not wf.get("isError")) and bool(steps) and all(
        s.get("status") == "ok" for s in steps)
    # 设备回执：ac_control 真的生效（sim_ac 已应用命令）
    ac = client.call_tool("get_ac_state", {}, caller="rehearsal_ac")
    ac_state: dict[str, Any] = {}
    try:
        ac_state = json.loads(_text(ac))
    except json.JSONDecodeError:
        pass
    ac_ok = ac_state.get("action") == "on"
    print(f"    get_ac_state → {ac_state}")
    scores[4] = (wf_ok and ac_ok,
                 f"steps={[s.get('status') for s in steps]}, "
                 f"ac_action={ac_state.get('action')}, "
                 f"ac_temp={ac_state.get('temperature')}")

    # ---------- 第五幕：安全拦截三连 ----------
    print("\n[第五幕] 安全拦截")
    inj = client.call_tool("file_search",
                           {"directory": str(HERE / "core"), "pattern": "x; rm -rf /"},
                           caller="rehearsal_inject")
    perm = client.call_tool("ac_control", {"action": "on"}, caller="rehearsal_perm",
                            permission_level=_READ)
    rl_codes: list[int] = []
    for _ in range(3):
        r = client.call_tool("get_temperature", {}, caller="rehearsal_ratelimit")
        rl_codes.append(_code(r) if r.get("isError") else 0)
    c_inj, c_perm = _code(inj), _code(perm)
    print(f"    注入 file_search → {c_inj} ({_text(inj)[:70]})")
    print(f"    越权 ac_control(read) → {c_perm} ({_text(perm)[:70]})")
    print(f"    限流 get_temperature ×3 → {rl_codes}")
    ok5 = c_inj == 1007 and c_perm == 1003 and 1004 in rl_codes
    scores[5] = (ok5, f"1007={c_inj}, 1003={c_perm}, 限流序列={rl_codes}")

    # ---------- 第六幕：CLI 反向生成脚本实跑 ----------
    print("\n[第六幕] CLI 反向生成脚本实跑")
    cli = HERE / "generated_cli" / "gen_get_temperature.py"
    rc4, out4 = _run_py([str(cli)])
    out4s = out4.strip()
    print(f"    {cli.name} → rc={rc4}, stdout={out4s[:80]!r}")
    try:
        cli_val = float(out4s.splitlines()[-1]) if out4s else None
    except (ValueError, IndexError):
        cli_val = None
    ok6 = rc4 == 0 and cli_val is not None
    scores[6] = (ok6, f"{cli.name} rc={rc4} 输出={out4s[:40]!r}")

    # ---------- 第七幕：审计界面 ----------
    print("\n[第七幕] 审计界面")
    dash = args.dashboard.rstrip("/")
    audit_html, wf_html = "", ""
    try:
        audit_html = httpx.get(f"{dash}/audit?limit=80", timeout=10).text
        wf_html = httpx.get(f"{dash}/workflows", timeout=10).text
    except Exception as e:
        errors.append(f"审计面板不可访问: {type(e).__name__}: {e}")
    has_blocked = "class='blocked'" in audit_html or 'class="blocked"' in audit_html
    has_code = "1007" in audit_html          # A2：错误码列（审计页应直接可见 1007）
    has_wf = "office_cooling" in wf_html
    print(f"    审计页 blocked 行: {has_blocked}；错误码 1007 可见: {has_code}；"
          f"工作流页含 office_cooling: {has_wf}")
    scores[7] = (has_blocked and has_code and has_wf,
                 f"blocked={has_blocked}, error_code_visible={has_code}, "
                 f"workflow_detail={has_wf}")

    # ---------- 评分 8：时长与稳定性 ----------
    elapsed = time.perf_counter() - t0
    ok8 = elapsed <= args.max_seconds and not errors
    scores[8] = (ok8, f"总耗时 {elapsed:.1f}s（上限 {args.max_seconds:.0f}s）"
                      + (f"；错误: {'; '.join(errors)}" if errors else "；无报错"))

    # ---------- 汇总 ----------
    print("\n" + "=" * 68)
    print(f"{'#':<3}{'结果':<6}{'评分项':<22}说明")
    print("-" * 68)
    names = {1: "P1-P6 就绪", 2: "第二幕 工具发现", 3: "第三幕 单工具三连",
             4: "第三幕 工作流闭环", 5: "第五幕 安全三连", 6: "第六幕 CLI 反向生成",
             7: "第七幕 审计可见", 8: "时长与稳定性"}
    passed = 0
    for i in sorted(scores):
        ok, detail = scores[i]
        passed += 1 if ok else 0
        print(f"{i:<3}{'✓' if ok else '✗':<6}{names[i]:<22}{detail}")
    print("-" * 68)
    print(f"完整度评分：{passed}/8")
    print("=" * 68)
    return 0 if passed == 8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
