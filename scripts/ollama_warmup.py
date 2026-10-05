"""Ollama 本地模型预热（演示前把 11GB 权重加载进显存并常驻）。

为什么需要单独预热：
  1. **首次请求要加载权重**（实测冷启动 4.3s，但若模型文件不在系统缓存则更久），
     演示时现场首次调用会表现为"卡住"；
  2. **必须与 Agent 使用同一个 num_ctx**（默认 16384）——Ollama 在 num_ctx 变化时
     会卸载重载模型，若预热用默认 4096、演示用 16384，预热等于白做；
  3. **keep_alive=-1** 让模型常驻显存，避免演示途中因空闲超时被卸载后重载。

用法：
    python -m scripts.ollama_warmup                       # 预热默认模型
    python -m scripts.ollama_warmup --model gemma4local:latest
    python -m scripts.ollama_warmup --check-only          # 只做可用性检查，不预热
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

DEFAULT_URL = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gemma4local:latest")
DEFAULT_NUM_CTX = int(os.environ.get("LLM_NUM_CTX", "16384"))


def _fail(msg: str) -> int:
    print(f"[ollama] ✗ {msg}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Ollama 本地模型预热")
    ap.add_argument("--url", default=DEFAULT_URL, help="Ollama 服务地址")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="模型名")
    ap.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX,
                    help="上下文窗口，必须与 Agent 一致（默认 16384）")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--check-only", action="store_true",
                    help="只检查服务与模型是否可用，不发送预热请求")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]

    with httpx.Client(timeout=args.timeout) as c:
        # 1) 服务可达性
        try:
            ver = c.get(f"{base}/api/version").json().get("version", "?")
        except Exception as e:  # noqa: BLE001 - 预热脚本需如实报告失败原因
            return _fail(f"Ollama 服务不可达（{base}）：{type(e).__name__}: {e}\n"
                         f"         请先启动：ollama serve")
        print(f"[ollama] 服务就绪：{base}（version {ver}）")

        # 2) 模型存在性
        try:
            tags = c.get(f"{base}/api/tags").json().get("models", [])
        except Exception as e:  # noqa: BLE001
            return _fail(f"读取模型列表失败：{type(e).__name__}: {e}")
        names = [m.get("name", "") for m in tags]
        if args.model not in names:
            return _fail(f"模型 {args.model} 不存在。已安装：{', '.join(names) or '（无）'}\n"
                         f"         请先拉取：ollama pull {args.model}")
        print(f"[ollama] 模型已安装：{args.model}（共 {len(names)} 个）")

        if args.check_only:
            print("[ollama] 仅检查模式，跳过预热")
            return 0

        # 3) 预热：与 Agent 完全相同的 num_ctx，并保持常驻
        t0 = time.time()
        try:
            resp = c.post(f"{base}/api/chat", json={
                "model": args.model,
                "messages": [{"role": "user", "content": "就绪确认，请只回复：ok"}],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_ctx": args.num_ctx, "num_predict": 8},
            })
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            return _fail(f"预热请求失败：{type(e).__name__}: {e}")
        dt = time.time() - t0
        print(f"[ollama] 预热完成：{dt:.1f}s（num_ctx={args.num_ctx}，keep_alive=-1）")

        # 4) 回读实际加载状态（确认显存占用与上下文窗口）
        try:
            ps = c.get(f"{base}/api/ps").json().get("models", [])
        except Exception:  # noqa: BLE001 - 状态回读失败不影响预热结论
            ps = []
        for m in ps:
            if m.get("name") == args.model or m.get("model") == args.model:
                vram = m.get("size_vram", 0) / (1024 ** 3)
                print(f"[ollama] 已常驻：ctx={m.get('context_length')}  "
                      f"显存占用 {vram:.2f} GB")
                if m.get("context_length") and m["context_length"] != args.num_ctx:
                    print(f"[ollama] ⚠ 实际上下文 {m.get('context_length')} "
                          f"与预期 {args.num_ctx} 不一致（可能被其他请求改过）")
                break

    print("[ollama] ✓ 本地 LLM 就绪，可执行："
          f"python -m agent.llm_agent --ollama --url http://127.0.0.1:8020")
    return 0


if __name__ == "__main__":
    sys.exit(main())