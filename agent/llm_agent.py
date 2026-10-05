"""LLM Agent —— 可插拔大模型驱动的 MCP 工具调用（SUP-01）。

定位与设计（答辩要点）：
1. **LLM 只负责决策**（选工具、定参数），所有调用必须经 MCP Gateway，
   Guard（参数校验/权限/限流/审计）对 LLM 与普通脚本一视同仁 ——
   平台安全不依赖 LLM 的可靠性，这是"Agent 只认识 MCP"的直接收益；
2. **LLM 后端可插拔**：任何 OpenAI Chat Completions 兼容服务均可接入
   （DeepSeek / 阿里百炼兼容模式 / Ollama / vLLM），
   通过 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY 环境变量切换，零代码改动；
3. **三级降级链**（演示永不中断）：
   原生 tool_calls（ReAct 闭环）→ 提示词 JSON 计划 → 确定性脚本模式。

本地模型（Ollama）实测结论（2026-09-26，gemma-4-26B-A4B IQ3_XXS）：
   - 原生 tool_calls 通道 6/6 通过，含"双字符串参数""引号赋值"两个已知易错用例；
   - 工具参数名与 Gemma 渲染器保留字无冲突（见 scripts/ollama_tool_probe.py）；
   - 提示词 JSON 计划通道可解析但多步规划不稳定（只返回首步），故仅作兜底。

用法：
    # 本地 Ollama（一条命令，无需配 Key）
    python -m agent.llm_agent --ollama --goal "会议室太热了，帮我降温到 26 度"

    # 云端 LLM（需先设置 DEEPSEEK_API_KEY 或 LLM_API_KEY）
    python -m agent.llm_agent --goal "会议室太热了，帮我降温到 26 度"

    # 强制提示词计划模式 / 脚本降级模式
    python -m agent.llm_agent --plan
    python -m agent.llm_agent --script
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from typing import Any

import httpx

from agent.demo_agent import MCPClient, _fmt_result

# ---- LLM 后端配置（环境变量可插拔）----

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 本地 Ollama 预设（--ollama 一键切换，无需配 Key）
OLLAMA_NATIVE_BASE = "http://localhost:11434"
OLLAMA_MODEL = "gemma4local:latest"

# 本地模型的上下文窗口。**这是本地部署最关键的一项**：Ollama 默认只加载
# 4096 上下文（实测 /api/ps 中 context_length=4096，而模型原生支持 262144），
# 而 11 个工具的 JSON Schema 加上多轮工具返回值很容易超过 4096 —— 溢出后
# Ollama 会截断最旧的 system 提示与用户目标，实测表现为模型遗忘目标并陷入
# "单轮吐出数十个相同工具调用"的重复退化。
#
# 但也不是越大越好：本机 RTX 5060 Ti（16GB）实测 65536 会让 KV cache 挤爆显存，
# 首次请求因模型重载 + 显存溢出超过 300s 超时；16384 稳定（占用 12.4GB，余 2.5GB）。
# 显存更充裕的机器可用环境变量 LLM_NUM_CTX 调大。
DEFAULT_NUM_CTX = 16384

# 重复惩罚：抑制量化模型的重复退化（1.0 = 不惩罚）
DEFAULT_REPEAT_PENALTY = 1.1

# 单次生成的最大 token 数（对齐 OpenAI 通道的 max_tokens）。
# 必须显式设置，否则原生通道无界生成（见 _post 注释）。
DEFAULT_NUM_PREDICT = 1024

# 每轮只执行 1 个工具调用（强制串行）。
#
# 为什么必须由代码强制，而不是靠提示词：实测本地量化模型会在同一轮里
# 批量发出 get_temperature + ac_control，**在还没看到温度结果时就做了
# 条件判断** —— 实测"只有当温度超过 35 度才开空调"的用例里，模型一边把
# 空调打开了，一边宣称"未达到 35 度，因此未开启空调"，条件分支形同虚设。
# 提示词里写"每轮只调用一个工具"并不能约束住它。
#
# 串行执行后，模型每轮必须基于真实返回值决策，这才是 ReAct 的语义，
# 也是本项目"Agent 先观察再决策"演示点的真实体现；代价是多一轮推理（约 2s）。
# 同时它天然抑制重复退化：即使模型吐出一串重复调用，也只执行第一个。
MAX_CALLS_PER_ROUND = 1

# 采样温度：工具调用要求确定性，取 0.0。
#
# 实测对比（同一模型 gemma-4-26B-A4B IQ3_XXS，目标"会议室太热了，帮我降温到 26 度"，
# 各 5 次）：temp=0.3 → 原生模式 3/5、动作正确 4/5、数值转述保真 0/5；
#             temp=0.0 → 原生模式 5/5、动作正确 5/5、数值转述保真 4/5。
# 温度对量化模型的影响不只是"格式稳定性"，更直接决定它会不会编造数值、
# 会不会谎称做了未做的操作；代价是平均耗时略增（12.3s → 22.6s），值得。
DEFAULT_TEMPERATURE = 0.0

SYSTEM_PROMPT = """你是一个办公环境管理 Agent，运行在 UniAgent Hub 之上。
你可以且只能通过下方的 MCP 工具列表完成用户目标（不允许编造不存在的工具）。

规则：
1. 输出必须是一个 JSON 数组，每个元素形如：
   {{"name": "工具名", "arguments": {{...}}, "reason": "一句话理由"}}
2. 按执行顺序排列；通常 1-3 步即可完成目标；
3. 只输出 JSON，不要输出任何其他文字或 markdown 代码块标记。"""

NATIVE_SYSTEM_PROMPT = """你是办公环境管理 Agent，运行在 UniAgent Hub 之上。
你可以且只能通过下方提供的工具完成用户目标，不允许编造工具名或参数。

规则：
1. 每轮只调用一个工具；平台每轮只执行你请求的第一个工具，其余会被丢弃；
2. 已经成功返回过结果的工具，不要用相同参数重复调用 —— 请推进到下一步或直接给出结论；
3. 拿到工具返回结果后再决定下一步 —— 涉及条件判断时（例如"超过 28 度才开空调"），
   必须先查到实际温度，确认条件成立后再调用相应工具；
4. 信息足够时直接用中文总结回答，不要再调用工具；
5. 工具返回错误时，向用户说明失败原因，不要用完全相同的参数重复调用；
6. 必须完成用户的全部要求（例如既要求查询又要求调节空调，就要两件事都做）；
7. 引用工具返回的数值时必须原样照抄，禁止改写、取整或凭印象重述；
8. 你的结论必须与你实际执行过的操作一致，不要声称做了未做的事；
9. 不要解释你的推理过程，直接调用工具或给出结论。"""

# Gemma 系模型在 Ollama 上会把模板控制 token 泄漏进 content。实测出现过三种形态：
#   "thought\n<channel|>会议室当前温度为 30.6 度…"
#   ">${thought}"
#   "<tool_call|><|tool_response>"
# 这些都属于模板渲染残留，直接打印会让演示看起来像乱码，故统一剥离。
_CHANNEL_TOKEN_RE = re.compile(
    r"<\|?\s*/?\s*(?:channel|thought|start_of_turn|end_of_turn"
    r"|tool_call|tool_response|tool)\s*\|?\s*>",
    re.IGNORECASE)
_TEMPLATE_VAR_RE = re.compile(r"\$\{[^}]{0,40}\}")      # ${thought} 等模板占位
_CHANNEL_LINE_RE = re.compile(r"^\s*(?:thought|final)\s*\n?", re.IGNORECASE | re.MULTILINE)
_LEADING_JUNK_RE = re.compile(r"^[\s>|$}{]+")
_MEANINGFUL_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)


def _clean_answer(text: str) -> str:
    """剥离模型输出中的模板控制 token；剥离后无实质内容则返回空串。

    返回空串会被调用方视为"模型未给出有效结论"并触发降级 ——
    这比把 `<tool_call|><|tool_response>` 这类垃圾当成结论打印出来要诚实得多。
    """
    if not text:
        return ""
    cleaned = _TEMPLATE_VAR_RE.sub("", _CHANNEL_TOKEN_RE.sub("", text))
    cleaned = _CHANNEL_LINE_RE.sub("", cleaned)
    # 清掉因剥离控制 token 残留在行首的孤立符号（如 ">${thought}" → ">"）
    cleaned = "\n".join(_LEADING_JUNK_RE.sub("", ln) if ln.strip() else ln
                        for ln in cleaned.splitlines()).strip()
    # 只剩标点/空白说明是纯模板残留，不算有效结论
    return cleaned if _MEANINGFUL_RE.search(cleaned) else ""


class OpenAICompatibleLLM:
    """OpenAI Chat Completions 兼容客户端（DeepSeek/百炼/Ollama 通用）。"""

    def __init__(self, api_key: str, base_url: str | None = None,
                 model: str | None = None, timeout: float = 120.0,
                 temperature: float | None = None) -> None:
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        env_temp = os.environ.get("LLM_TEMPERATURE")
        self.temperature = (temperature if temperature is not None
                            else float(env_temp) if env_temp
                            else DEFAULT_TEMPERATURE)
        # 本地模型首次推理需加载权重（11GB 量化约 60s），超时放宽；
        # 云端按 60s 足够，这里统一由 --timeout / LLM_TIMEOUT 控制
        self._http = httpx.Client(timeout=timeout)

    def chat(self, system: str, user: str) -> str:
        resp = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.temperature,
                "max_tokens": 1024,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def chat_messages(self, messages: list[dict],
                      tools: list[dict] | None = None) -> dict:
        """原生 tool_calls 通道：返回 assistant message（可能含 tool_calls）。

        messages 为完整多轮上下文（含历史 tool 角色消息），
        由调用方维护，以便模型基于工具返回值做下一步决策。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 1024,
        }
        if tools:
            payload["tools"] = tools
        resp = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


def _llm_from_env(ollama: bool = False) -> Any:
    """构造 LLM 客户端。

    --ollama 时使用 Ollama 原生通道（可设置 num_ctx，见 OllamaNativeLLM 说明）；
    否则读环境变量 Key，未配置返回 None（降级信号）。
    """
    if ollama:
        return OllamaNativeLLM(
            base_url=os.environ.get("LLM_BASE_URL") or OLLAMA_NATIVE_BASE,
            model=os.environ.get("LLM_MODEL") or OLLAMA_MODEL)
    key = (os.environ.get("LLM_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY")
           or os.environ.get("DASHSCOPE_API_KEY"))
    if not key:
        return None
    return OpenAICompatibleLLM(key)


class OllamaNativeLLM:
    """Ollama 原生 /api/chat 客户端（本地模型专用通道）。

    为什么不直接用 /v1 兼容层：OpenAI 兼容层无法传递 `options`，而
    `options.num_ctx` 是本地部署的关键——Ollama 默认只加载 4096 上下文
    （实测该模型原生支持 262144），11 个工具的 Schema 加多轮工具返回值
    轻易溢出；溢出后 Ollama 截断最旧的 system 提示与用户目标，模型随即
    遗忘目标并陷入重复调用退化。原生通道还可关闭 think 通道、设置
    repeat_penalty，这两项直接对应已知的 Gemma 格式稳定性问题。

    对外暴露与 OpenAICompatibleLLM 相同的 chat / chat_messages 接口，
    消息统一用 OpenAI 结构（assistant.tool_calls / role=tool），
    工具结果格式差异在 _to_ollama / _to_openai 内消化。
    """

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 timeout: float = 120.0, temperature: float | None = None,
                 num_ctx: int | None = None,
                 repeat_penalty: float | None = None) -> None:
        # 容错：用户可能把 /v1 后缀一起填进来
        self.base_url = (base_url or OLLAMA_NATIVE_BASE).rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = model or OLLAMA_MODEL
        env_temp = os.environ.get("LLM_TEMPERATURE")
        self.temperature = (temperature if temperature is not None
                            else float(env_temp) if env_temp
                            else DEFAULT_TEMPERATURE)
        self.num_ctx = num_ctx or int(os.environ.get("LLM_NUM_CTX",
                                                     DEFAULT_NUM_CTX))
        self.num_predict = int(os.environ.get("LLM_NUM_PREDICT",
                                              DEFAULT_NUM_PREDICT))
        self.repeat_penalty = (repeat_penalty if repeat_penalty is not None
                               else float(os.environ.get("LLM_REPEAT_PENALTY",
                                                        DEFAULT_REPEAT_PENALTY)))
        self._think = os.environ.get("OLLAMA_THINK", "0") == "1"
        self._http = httpx.Client(timeout=timeout)

    # ---- 对外接口（与 OpenAICompatibleLLM 对齐）----

    def chat(self, system: str, user: str) -> str:
        msg = self._post([{"role": "system", "content": system},
                          {"role": "user", "content": user}], None)
        return msg.get("content") or ""

    def chat_messages(self, messages: list[dict],
                      tools: list[dict] | None = None) -> dict:
        return self._to_openai(self._post(self._to_ollama(messages), tools))

    # ---- 报文转换 ----

    @staticmethod
    def _to_ollama(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                # Ollama 不要求 tool_call_id（其 tool_calls 无 id 概念）
                out.append({"role": "tool", "content": m.get("content", "")})
            elif role == "assistant" and m.get("tool_calls"):
                out.append({
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [{
                        "function": {
                            "name": c["function"]["name"],
                            "arguments": _parse_tool_args(
                                c["function"].get("arguments")),
                        }} for c in m["tool_calls"]],
                })
            else:
                out.append({"role": role, "content": m.get("content", "")})
        return out

    @staticmethod
    def _to_openai(msg: dict) -> dict:
        """Ollama 的 tool_calls 无 id、arguments 为对象 → 归一化为 OpenAI 结构。"""
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or [], 1):
            fn = c.get("function", {})
            calls.append({
                "id": f"ollama_{i}",
                "type": "function",
                "function": {"name": fn.get("name", ""),
                             "arguments": fn.get("arguments")
                                            or fn.get("arguments_json") or {}},
            })
        return {"role": "assistant", "content": msg.get("content") or "",
                "tool_calls": calls}

    def _post(self, messages: list[dict], tools: list[dict] | None) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
                "repeat_penalty": self.repeat_penalty,
                # 必须限制输出长度：Ollama 原生 options 没有 max_tokens 的默认值，
                # 不加 num_predict 时模型一旦进入退化生成（实测会泄漏控制 token
                # 并持续输出），单次请求可长达数分钟 → 触发超时并整体降级。
                # 1024 与 OpenAI 通道的 max_tokens 对齐。
                "num_predict": self.num_predict,
            },
        }
        if tools:
            payload["tools"] = tools
        if self._think:
            payload["think"] = True
        resp = self._http.post(f"{self.base_url}/api/chat", json=payload)
        if resp.status_code == 400 and "think" in payload:
            # 部分模型不支持 thinking：去掉该字段重试一次
            payload.pop("think")
            resp = self._http.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {})




def _extract_json_array(text: str) -> list[dict]:
    """从 LLM 输出中稳健提取 JSON 数组（容忍 markdown 代码块包裹）。"""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError(f"LLM 输出中未找到 JSON 数组: {text[:200]}")
    plan = json.loads(text[start:end + 1])
    if not isinstance(plan, list) or not all(
            isinstance(s, dict) and "name" in s for s in plan):
        raise ValueError("LLM 计划格式非法（需为含 name 字段的对象数组）")
    return plan


class LLMAgent:
    """决策（LLM）与执行（MCP Client）分离的 Agent。"""

    def __init__(self, client: MCPClient, llm: OpenAICompatibleLLM) -> None:
        self.client = client
        self.llm = llm
        self._t0 = 0.0

    def plan(self, goal: str, tools: list[dict]) -> list[dict]:
        tools_desc = json.dumps(
            [{"name": t["name"], "description": t.get("description", ""),
              "inputSchema": t.get("inputSchema", {})} for t in tools],
            ensure_ascii=False)
        raw = self.llm.chat(SYSTEM_PROMPT,
                            f"可用工具：\n{tools_desc}\n\n用户目标：{goal}")
        return _extract_json_array(raw)

    def run(self, goal: str, permission_level: str = "write") -> None:
        """提示词 JSON 计划模式（一次性规划 → 顺序执行，不观察中间结果）。"""
        tools = self.client.list_tools()
        print(f"[agent] 工具发现：{len(tools)} 个工具 "
              f"({', '.join(t['name'] for t in tools)})")

        print(f"[agent] 目标：{goal}")
        print("[agent] 请求 LLM 生成执行计划…")
        steps = self.plan(goal, tools)
        print(f"[agent] 计划（{len(steps)} 步）：")
        for i, s in enumerate(steps, 1):
            print(f"    {i}. {s['name']}({json.dumps(s.get('arguments', {}),
                                                  ensure_ascii=False)})"
                  f" — {s.get('reason', '')}")

        print("[agent] 经 MCP Gateway 逐步执行（Guard 横切校验）：")
        for i, s in enumerate(steps, 1):
            res = self.client.call_tool(
                s["name"], s.get("arguments", {}),
                caller="llm_agent", permission_level=permission_level)
            print(f"    {i}. {_fmt_result(res)}")

    def run_native(self, goal: str, permission_level: str = "write",
                   max_rounds: int = 8) -> None:
        """原生 tool_calls 模式（ReAct 闭环：观察工具返回值后再决策下一步）。

        这是本地/云端支持 function calling 模型的首选模式 ——
        与计划模式的区别在于"每轮真实观察结果再决策"，
        因此能正确处理条件分支（例如温度未超阈值就不开空调）。
        """
        tools = self.client.list_tools()
        print(f"[agent] 工具发现：{len(tools)} 个工具 "
              f"({', '.join(t['name'] for t in tools)})")
        print(f"[agent] 模式：原生 tool_calls（ReAct 闭环，最多 {max_rounds} 轮）")
        print(f"[agent] 目标：{goal}")
        self._t0 = time.time()

        tool_defs = [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema")
                              or {"type": "object", "properties": {}},
            },
        } for t in tools]

        messages: list[dict] = [
            {"role": "system", "content": NATIVE_SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ]
        executed: dict[tuple[str, str], str] = {}   # (工具名, 参数) -> 结果文本

        for round_no in range(1, max_rounds + 1):
            msg = self.llm.chat_messages(messages, tool_defs)
            calls = msg.get("tool_calls") or []
            if not calls:
                answer = _clean_answer(msg.get("content") or "")
                print(f"[agent] 第 {round_no} 轮：模型给出结论（不再调用工具）")
                if answer:
                    print(f"[agent] 结论：{answer}")
                else:
                    raise ValueError("模型既未调用工具也未给出结论（空响应）")
                print(f"[agent] 完成，共 {round_no} 轮 / {time.time() - self._t0:.1f}s")
                return

            # 先裁掉超量请求再写回上下文：否则 assistant 消息里挂着几十个
            # tool_calls 却只有少量 tool 结果，上下文既不合法又进一步膨胀。
            #
            # 关键：不能静默丢弃——实测模型会反复重新请求被丢掉的调用，
            # 直到耗尽轮数并整体降级（3/3 复现）。故在工具结果里附上明确的
            # 平台说明，让模型知道"本轮只执行了第 1 个"，从而正常推进。
            over = len(calls) - MAX_CALLS_PER_ROUND
            if over > 0:
                print(f"[agent] 第 {round_no} 轮：模型请求调用 {len(calls)} 个工具，"
                      f"⚠ 串行执行只保留第 1 个（丢弃 {over} 个，防重复退化）")
                calls = calls[:MAX_CALLS_PER_ROUND]
            else:
                print(f"[agent] 第 {round_no} 轮：模型请求调用 {len(calls)} 个工具")

            messages.append({"role": "assistant",
                             "content": msg.get("content") or "",
                             "tool_calls": calls})

            note = ""
            if over > 0:
                note = (f"\n\n[平台说明] 平台按串行策略本轮只执行了这 1 个调用，"
                        f"你请求的另外 {over} 个调用未执行。"
                        f"请基于以上结果决定下一步（如仍需执行，请再次请求）。")

            for idx, call in enumerate(calls, 1):
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = _parse_tool_args(fn.get("arguments"))
                key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))

                # 相同调用只真正执行一次：既避免把 Hub 打成限流风暴，
                # 也避免把重复的错误信息灌回上下文（会加剧模型重复退化）
                if key in executed:
                    print(f"    {round_no}.{idx} tools/call {name}"
                          f"({json.dumps(args, ensure_ascii=False)}) —— 已调用过，复用结果")
                    content = (executed[key] + "\n\n[平台说明] 该调用与你之前完全相同，"
                               "平台未重复执行（结果同上）。请不要重复请求同一个工具："
                               "若目标尚未完成，请改用其他工具；若已完成，请直接给出结论。")
                else:
                    print(f"    {round_no}.{idx} tools/call {name}"
                          f"({json.dumps(args, ensure_ascii=False)})")
                    res = self.client.call_tool(
                        name, args, caller="llm_agent",
                        permission_level=permission_level)
                    print(f"        {_fmt_result(res)}")
                    executed[key] = _tool_result_text(res)
                    content = executed[key] + note

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id") or f"call_{round_no}_{idx}",
                    "content": content,
                })

        raise ValueError(f"超过最大轮数 {max_rounds}，模型未收敛")


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    """解析 tool_call 的 arguments。

    OpenAI 规范里 arguments 是 JSON 字符串（Ollama 兼容层实测亦然，
    见 docs/evidence/ollama_probe_1.json Q2）；部分实现直接给对象。
    两种都兼容，非法/空值退化为空参数（交由 Hub Guard 校验并如实报错）。
    """
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_result_text(res: dict) -> str:
    """把 MCP 返回转成回灌给模型的文本（错误也如实回灌，让模型自行调整）。"""
    meta = res.get("meta", {})
    text = res["content"][0]["text"] if res.get("content") else ""
    if res.get("isError"):
        return f"[调用失败 error_code={meta.get('error_code')}] {text}"
    return text


def run_script_mode(client: MCPClient) -> None:
    """确定性脚本模式（无 Key 降级 / 演示兜底，链路与 LLM 模式完全一致）。"""
    tools = client.list_tools()
    print(f"[agent] 脚本降级模式（未配置 LLM_API_KEY）\n"
          f"[agent] 工具发现：{len(tools)} 个工具 "
          f"({', '.join(t['name'] for t in tools)})")

    print("[agent] 固定剧本：查温度 → 温度过高则触发降温工作流")
    res = client.call_tool("get_temperature", {},
                           caller="llm_agent", permission_level="read")
    print(f"    1. {_fmt_result(res)}")
    if res.get("isError"):
        print("    （传感器离线，剧本终止）")
        return
    temp = res["content"][0]["text"]
    try:
        t = float(temp)
    except (TypeError, ValueError):
        t = 0.0
    if t > 28:
        res = client.call_tool(
            "run_workflow", {"workflow": "office_cooling"},
            caller="llm_agent", permission_level="write")
        print(f"    2. 温度 {t}°C > 28°C → 触发 office_cooling：{_fmt_result(res)}")
    else:
        print(f"    2. 温度 {t}°C ≤ 28°C，无需降温")


def main() -> None:
    parser = argparse.ArgumentParser(description="UniAgent Hub LLM Agent")
    parser.add_argument("--url", default="http://127.0.0.1:8000",
                        help="Hub 服务源地址（不含 /mcp 后缀）")
    parser.add_argument("--goal", default="查询会议室温度，如果超过 28 度就开空调降温到 26 度",
                        help="自然语言目标（LLM 模式）")
    parser.add_argument("--ollama", action="store_true",
                        help="使用本地 Ollama（默认 http://localhost:11434/v1，无需 API Key）")
    parser.add_argument("--plan", action="store_true",
                        help="强制提示词 JSON 计划模式（默认优先原生 tool_calls）")
    parser.add_argument("--script", action="store_true",
                        help="强制脚本降级模式（忽略 API Key）")
    parser.add_argument("--timeout", type=float,
                        default=float(os.environ.get("LLM_TIMEOUT", "60")),
                        help="单次 LLM 请求超时秒数（默认 60s；模型已预热时实测单轮 1-5s）")
    args = parser.parse_args()

    client = MCPClient(args.url)
    llm = None if args.script else _llm_from_env(args.ollama)

    print("=" * 60)
    print("UniAgent Hub LLM Agent — 决策与执行分离，安全不依赖 LLM")
    print("=" * 60)

    if llm is None:
        run_script_mode(client)
        return

    llm._http.timeout = httpx.Timeout(args.timeout)  # noqa: SLF001 - CLI 覆盖超时
    detail = f"[agent] LLM 后端：{llm.base_url}  模型：{llm.model}  温度：{llm.temperature}"
    if hasattr(llm, "num_ctx"):
        detail += (f"  num_ctx：{llm.num_ctx}"
                   f"  repeat_penalty：{llm.repeat_penalty}")
    print(detail)

    agent = LLMAgent(client, llm)
    try:
        if args.plan:
            agent.run(args.goal)
        else:
            agent.run_native(args.goal)
    except (ValueError, httpx.HTTPError, KeyError) as e:
        print(f"[agent] 原生 tool_calls 模式失败（{type(e).__name__}: {e}）")
        print("[agent] 降级为提示词计划模式：")
        try:
            agent.run(args.goal)
        except (ValueError, httpx.HTTPError, KeyError) as e2:
            print(f"[agent] 计划模式亦失败（{type(e2).__name__}: {e2}）")
            print("[agent] 最终降级为确定性脚本模式：")
            run_script_mode(client)


if __name__ == "__main__":
    main()
