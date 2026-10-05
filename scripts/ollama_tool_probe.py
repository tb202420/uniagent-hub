"""Ollama 本地模型工具调用能力探针（阶段 4 · LLM 本地化选型验证）。

目的：在适配 agent/llm_agent.py 之前，用实测数据回答三个问题：

  Q1 模型返回原生 tool_calls 吗？（Ollama 原生 /api/chat 通道）
  Q2 模型在 OpenAI 兼容通道（/v1/chat/completions）上返回 tool_calls 吗？
      —— llm_agent.py 当前走的就是这条通道
  Q3 现有"提示词让模型输出 JSON 计划"的方案（SYSTEM_PROMPT + _extract_json_array）
      在这台本地模型上是否可用？—— 这是零代码改动就能跑通的前提

背景：已知 Gemma 系在 Ollama 上有三个格式稳定性问题
  - key=value 赋值解析失败（工具含 ≥2 个字符串参数时触发）
  - 尾随垃圾 token 导致合法 tool call 被整条丢弃
  - thinking 模式下调用一次后停止（CUDA）
因此探针额外对比 温度 0.0 / 0.3 / 0.4 与 think=True/False。

用法：
    python -m scripts.ollama_tool_probe                      # 用内置 schema（离线可用）
    python -m scripts.ollama_tool_probe --hub http://127.0.0.1:8020   # 用 Hub 真实 tools/list
    python -m scripts.ollama_tool_probe --only q1            # 只跑某一组
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

DEFAULT_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4local:latest")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "65536"))
REQUEST_TIMEOUT = float(os.environ.get("OLLAMA_PROBE_TIMEOUT", "600"))
# 探针提示词中的搜索目录：跟随当前工作目录（可移植，不再绑定开发机路径）
_DEMO_DIR = os.getcwd()

# ---- 内置工具 schema（与 Hub 真实 tools/list 同构；含双字符串参数以触发已知 bug）----
FALLBACK_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_temperature",
            "description": "获取办公区温度传感器当前读数（摄氏度）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_search",
            "description": "在指定目录下按文件名模式搜索文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "搜索目录"},
                    "pattern": {"type": "string", "description": "文件名模式"},
                },
                "required": ["directory", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ac_control",
            "description": "控制空调开关与目标温度",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off"],
                               "description": "开关动作"},
                    "temperature": {"type": "number",
                                    "description": "目标温度（16-30 摄氏度）"},
                },
                "required": ["action"],
            },
        },
    },
]

# ---- 现有 llm_agent.py 的提示词方案（原样搬运，用于验证零改动可行性）----
LEGACY_SYSTEM_PROMPT = """你是一个办公环境管理 Agent，运行在 UniAgent Hub 之上。
你可以且只能通过下方的 MCP 工具列表完成用户目标（不允许编造不存在的工具）。

规则：
1. 输出必须是一个 JSON 数组，每个元素形如：
   {{"name": "工具名", "arguments": {{...}}, "reason": "一句话理由"}}
2. 按执行顺序排列；通常 1-3 步即可完成目标；
3. 只输出 JSON，不要输出任何其他文字或 markdown 代码块标记。"""


def tools_from_hub(hub: str) -> list[dict[str, Any]]:
    """从运行中的 Hub 拉取真实 tools/list，转换成 OpenAI 工具定义格式。"""
    resp = httpx.post(f"{hub.rstrip('/')}/mcp", timeout=10, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    resp.raise_for_status()
    raw = resp.json()["result"]["tools"]
    out = []
    for t in raw:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object",
                                                    "properties": {}}),
            },
        })
    return out


def _short(obj: Any, n: int = 320) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def probe_ollama_native(client: httpx.Client, base: str, model: str,
                        goal: str, tools: list[dict], temperature: float,
                        think: bool | None) -> dict[str, Any]:
    """Q1：Ollama 原生 /api/chat 通道（支持 options.num_ctx 与 think 开关）。"""
    options: dict[str, Any] = {"temperature": temperature, "num_ctx": NUM_CTX}
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": goal}],
        "tools": tools,
        "stream": False,
        "options": options,
    }
    if think is not None:
        payload["think"] = think
    t0 = time.time()
    resp = client.post(f"{base}/api/chat", json=payload)
    dt = time.time() - t0
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "raw": _short(resp.text)}
    data = resp.json()
    msg = data.get("message", {})
    return {
        "ok": True,
        "http": resp.status_code,
        "elapsed": round(dt, 2),
        "tool_calls": msg.get("tool_calls"),
        "has_thinking_field": "thinking" in msg and bool(msg.get("thinking")),
        "content": _short(msg.get("content") or "", 400),
        "done_reason": data.get("done_reason"),
        "eval_count": data.get("eval_count"),
    }


def probe_openai_compat(client: httpx.Client, base: str, model: str,
                        goal: str, tools: list[dict],
                        temperature: float) -> dict[str, Any]:
    """Q2：OpenAI 兼容通道（llm_agent.py 当前使用的通道）。"""
    t0 = time.time()
    resp = client.post(
        f"{base}/v1/chat/completions",
        headers={"Authorization": "Bearer ollama"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": goal}],
            "tools": tools,
            "temperature": temperature,
            "max_tokens": 1024,
        })
    dt = time.time() - t0
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "raw": _short(resp.text)}
    msg = resp.json()["choices"][0]["message"]
    return {
        "ok": True,
        "http": resp.status_code,
        "elapsed": round(dt, 2),
        "tool_calls": msg.get("tool_calls"),
        "finish_reason": resp.json()["choices"][0].get("finish_reason"),
        "content": _short(msg.get("content") or "", 400),
    }


def probe_legacy_text_plan(client: httpx.Client, base: str, model: str,
                           goal: str, tools: list[dict],
                           temperature: float,
                           think: bool | None = None) -> dict[str, Any]:
    """Q3：现有提示词方案——模型是否按 SYSTEM_PROMPT 输出合法 JSON 计划数组。"""
    tools_desc = json.dumps(
        [{"name": t["function"]["name"],
          "description": t["function"].get("description", ""),
          "inputSchema": t["function"].get("parameters", {})} for t in tools],
        ensure_ascii=False)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": LEGACY_SYSTEM_PROMPT},
            {"role": "user",
             "content": f"可用工具：\n{tools_desc}\n\n用户目标：{goal}"},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": NUM_CTX},
    }
    if think is not None:
        payload["think"] = think
    t0 = time.time()
    resp = client.post(f"{base}/api/chat", json=payload)
    dt = time.time() - t0
    if resp.status_code != 200:
        return {"ok": False, "http": resp.status_code, "raw": _short(resp.text)}
    content = resp.json().get("message", {}).get("content") or ""
    # 复用 llm_agent.py 的真实提取逻辑
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from agent.llm_agent import _extract_json_array
    parsed: Any = None
    parse_err: str | None = None
    try:
        parsed = _extract_json_array(content)
        if not parsed:
            parse_err = "解析成功但为空数组"
    except Exception as e:  # noqa: BLE001 - 探针需如实记录失败原因
        parse_err = f"{type(e).__name__}: {e}"
    return {
        "ok": True,
        "http": resp.status_code,
        "elapsed": round(dt, 2),
        "parsed": parsed,
        "parse_error": parse_err,
        "content": _short(content, 500),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Ollama 工具调用能力探针")
    ap.add_argument("--base", default=DEFAULT_BASE, help="Ollama 服务地址")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="模型名")
    ap.add_argument("--hub", default=None,
                    help="Hub 地址（如 http://127.0.0.1:8020），用真实 tools/list")
    ap.add_argument("--only", default=None, help="只跑指定组：q1 / q2 / q3")
    ap.add_argument("--out", default=None, help="结果 JSON 落盘路径")
    args = ap.parse_args()

    tools = FALLBACK_TOOLS
    tool_source = "内置 schema（3 个工具）"
    if args.hub:
        try:
            tools = tools_from_hub(args.hub)
            tool_source = f"Hub 真实 tools/list（{len(tools)} 个工具）"
        except Exception as e:  # noqa: BLE001 - 探针需如实记录失败原因
            print(f"[warn] 从 Hub 拉取工具失败（{e}），回退内置 schema")

    print("=" * 72)
    print("Ollama 工具调用能力探针")
    print(f"  Ollama : {args.base}   模型: {args.model}   num_ctx: {NUM_CTX}")
    print(f"  工具源 : {tool_source}")
    print("=" * 72)

    results: dict[str, Any] = {"model": args.model, "tool_source": tool_source,
                               "tool_count": len(tools), "tests": []}
    with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
        def record(tag: str, goal: str, **extra: Any) -> dict[str, Any]:
            results["tests"].append({"tag": tag, "goal": goal, **extra})
            return extra

        if args.only in (None, "q1"):
            print("\n---- Q1 原生 tool_calls（Ollama /api/chat）----")
            cases = [
                ("单工具·无参数", "会议室现在多少度？用工具查一下。", 0.3, False),
                ("双字符串参数（已知 bug 触发）",
                 f"帮我在 {_DEMO_DIR} 目录下搜索所有 .py 文件。", 0.3, False),
                ("引号赋值（最易触发 bug）",
                 f"搜索目录 directory='{_DEMO_DIR}'，pattern='*.py'", 0.3, False),
                ("温度 0.0 对照", f"帮我在 {_DEMO_DIR} 目录下搜索所有 .py 文件。",
                 0.0, False),
                ("温度 0.4", f"帮我在 {_DEMO_DIR} 目录下搜索所有 .py 文件。",
                 0.4, False),
                ("think=True（被动行为验证）", "会议室热，帮我开空调并调到 26 度。",
                 0.3, True),
            ]
            for name, goal, temp, think in cases:
                print(f"\n  [{name}] temp={temp} think={think}")
                try:
                    r = probe_ollama_native(c, args.base, args.model, goal, tools,
                                            temp, think)
                except Exception as e:  # noqa: BLE001
                    r = {"ok": False, "exception": f"{type(e).__name__}: {e}"}
                record(f"q1:{name}", goal, temperature=temp, think=think, **r)
                _print_native(r)

        if args.only in (None, "q2"):
            print("\n---- Q2 OpenAI 兼容通道（/v1/chat/completions）----")
            goal = f"帮我在 {_DEMO_DIR} 目录下搜索所有 .py 文件。"
            print(f"\n  [双字符串参数] temp=0.3")
            try:
                r = probe_openai_compat(c, args.base, args.model, goal, tools, 0.3)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "exception": f"{type(e).__name__}: {e}"}
            record("q2:双字符串参数", goal, temperature=0.3, **r)
            _print_native(r)

        if args.only in (None, "q3"):
            print("\n---- Q3 现有提示词 JSON 计划方案（零改动可行性）----")
            cases = [
                ("单工具", "会议室现在多少度？用工具查一下。", 0.0, False),
                ("双字符串参数",
                 f"帮我在 {_DEMO_DIR} 目录下搜索所有 .py 文件。", 0.3, False),
                ("多步（温度→空调）", "会议室太热了，如果超过 28 度就开空调调到 26 度。",
                 0.3, False),
            ]
            for name, goal, temp, think in cases:
                print(f"\n  [{name}] temp={temp}")
                try:
                    r = probe_legacy_text_plan(c, args.base, args.model, goal, tools,
                                               temp, think)
                except Exception as e:  # noqa: BLE001
                    r = {"ok": False, "exception": f"{type(e).__name__}: {e}"}
                record(f"q3:{name}", goal, temperature=temp, **r)
                if r.get("parsed"):
                    print(f"    ✅ 解析成功: {_short(r['parsed'])}  ({r['elapsed']}s)")
                else:
                    print(f"    ❌ 解析失败: {r.get('parse_error')}  ({r.get('elapsed')}s)")
                    print(f"       原始输出: {r.get('content')}")

    print("\n" + "=" * 72)
    print("结论摘要")
    q1 = [t for t in results["tests"] if t["tag"].startswith("q1:")]
    q2 = [t for t in results["tests"] if t["tag"].startswith("q2:")]
    q3 = [t for t in results["tests"] if t["tag"].startswith("q3:")]
    print(f"  Q1 原生 tool_calls ： {sum(1 for t in q1 if t.get('tool_calls'))}/{len(q1)} 成功")
    print(f"  Q2 OpenAI 兼容通道 ： {sum(1 for t in q2 if t.get('tool_calls'))}/{len(q2)} 成功")
    print(f"  Q3 提示词 JSON 计划： {sum(1 for t in q3 if t.get('parsed'))}/{len(q3)} 成功")
    print("=" * 72)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"结果已落盘：{args.out}")
    return 0


def _print_native(r: dict[str, Any]) -> None:
    if not r.get("ok"):
        print(f"    ✗ 失败: {r}")
        return
    calls = r.get("tool_calls")
    if calls:
        names = [c.get("function", {}).get("name") for c in calls]
        print(f"    ✅ 原生 tool_calls: {names}  ({r['elapsed']}s)")
        print(f"       参数: {_short([c.get('function', {}).get('arguments')
                                     for c in calls])}")
    else:
        print(f"    ❌ 无 tool_calls  ({r.get('elapsed')}s) "
              f"done_reason={r.get('done_reason')} finish={r.get('finish_reason')}")
        print(f"       文本: {r.get('content')}")
    if r.get("has_thinking_field"):
        print("       ⚠️ 返回 thinking 字段（CUDA 上可能被动）")


if __name__ == "__main__":
    sys.exit(main())
