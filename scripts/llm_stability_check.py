"""LLM Agent 稳定性批量测试（本地 Ollama 模型）。

目的：演示前量化本地量化模型的可靠性——单次成功不能说明问题，
需要连续 N 次统计：调用成功率、温度转述保真度、重复退化发生率、耗时。

用法：
    python -m scripts.llm_stability_check --runs 5 --url http://127.0.0.1:8020
    python -m scripts.llm_stability_check --runs 5 --goal "只查询温度，不要调空调"
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

TOOL_TEMP_RE = re.compile(r"tools/call get_temperature\(\{\}\)\s*\n\s*✓ ([\d.]+)")
ANSWER_TEMP_RE = re.compile(r"结论：.*?([\d.]+)\s*度")
DEGEN_RE = re.compile(r"疑似重复退化")
AC_RE = re.compile(r"tools/call ac_control\(([^)]*)\)")


def run_once(python: str, url: str, goal: str, extra: list[str]) -> dict:
    t0 = time.time()
    proc = subprocess.run(
        [python, "-u", "-m", "agent.llm_agent", "--ollama", "--url", url,
         "--goal", goal, *extra],
        cwd=HERE, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900)
    out = proc.stdout + proc.stderr
    dt = time.time() - t0

    tool_temps = TOOL_TEMP_RE.findall(out)
    answers = ANSWER_TEMP_RE.findall(out)
    ac_calls = AC_RE.findall(out)
    return {
        "seconds": round(dt, 1),
        "tool_temp": tool_temps[0] if tool_temps else None,
        "answer_temp": answers[0] if answers else None,
        "ac_called": bool(ac_calls),
        "ac_args": ac_calls[0] if ac_calls else None,
        "degenerate": bool(DEGEN_RE.search(out)),
        "native_ok": "原生 tool_calls 模式失败" not in out,
        "concluded": "结论：" in out,
        "raw": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM Agent 稳定性批量测试")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--url", default="http://127.0.0.1:8020")
    ap.add_argument("--goal",
                    default="会议室温度是多少？如果超过 28 度，就开空调调到 26 度")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="传给子进程的 LLM_TIMEOUT")
    ap.add_argument("--expect-no-ac", action="store_true",
                    help="断言不应调用 ac_control（条件分支用例：阈值未达成）")
    ap.add_argument("--out", default=None, help="原始输出落盘目录")
    args = ap.parse_args()

    print("=" * 76)
    print(f"LLM Agent 稳定性批量测试：{args.runs} 次")
    print(f"  目标：{args.goal}")
    if args.expect_no_ac:
        print("  断言：条件未达成 → 不应调用 ac_control")
    print("  注意：必须串行执行，Ollama 会排队处理并发请求（并发会导致超时）")
    print("=" * 76)

    results = []
    for i in range(1, args.runs + 1):
        print(f"\n---- 第 {i}/{args.runs} 次 ----")
        try:
            r = run_once(args.python, args.url, args.goal,
                         ["--timeout", str(args.timeout)])
        except subprocess.TimeoutExpired:
            r = {"seconds": 900, "tool_temp": None, "answer_temp": None,
                 "ac_called": False, "ac_args": None, "degenerate": False,
                 "native_ok": False, "concluded": False, "raw": "(超时)"}
        results.append(r)
        faithful = (r["tool_temp"] is not None and r["answer_temp"] is not None
                    and abs(float(r["tool_temp"]) - float(r["answer_temp"])) < 0.05)
        branch_ok = (not r["ac_called"]) if args.expect_no_ac else r["ac_called"]
        print(f"  耗时 {r['seconds']}s | 原生模式 {'✓' if r['native_ok'] else '✗'}"
              f" | 工具温度 {r['tool_temp']} | 转述温度 {r['answer_temp']}"
              f" | 数值保真 {'✓' if faithful else '✗'}"
              f" | 调空调 {'是' if r['ac_called'] else '否'}"
              + (f" | 分支正确 {'✓' if branch_ok else '✗'}" if args.expect_no_ac else
                 f" | 动作正确 {'✓' if branch_ok else '✗'}")
              + f" | 重复退化 {'有' if r['degenerate'] else '无'}")
        if args.out:
            p = Path(args.out)
            p.mkdir(parents=True, exist_ok=True)
            (p / f"llm_run_{i}.txt").write_text(r["raw"], encoding="utf-8")

    n = len(results)
    ok_native = sum(1 for r in results if r["native_ok"])
    ok_conc = sum(1 for r in results if r["concluded"])
    ok_faith = sum(1 for r in results
                   if r["tool_temp"] and r["answer_temp"]
                   and abs(float(r["tool_temp"]) - float(r["answer_temp"])) < 0.05)
    degen = sum(1 for r in results if r["degenerate"])
    ac_ok = sum(1 for r in results
                if ((not r["ac_called"]) if args.expect_no_ac else r["ac_called"]))
    avg = sum(r["seconds"] for r in results) / n

    print("\n" + "=" * 76)
    print("汇总")
    print(f"  原生 tool_calls 模式成功：{ok_native}/{n}")
    print(f"  给出结论             ：{ok_conc}/{n}")
    print(f"  数值转述保真         ：{ok_faith}/{n}")
    print(f"  {'分支判断正确' if args.expect_no_ac else '正确调用 ac_control'}       "
          f"：{ac_ok}/{n}")
    print(f"  出现重复退化         ：{degen}/{n}")
    print(f"  平均耗时             ：{avg:.1f}s")
    print("=" * 76)
    return 0 if (ok_native == n and ok_conc == n and ok_faith == n
                 and ac_ok == n) else 1


if __name__ == "__main__":
    sys.exit(main())