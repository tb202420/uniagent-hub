"""终端 token（v3.0 安全增量）。

攻击面：PTY 终端引入后，会话劫持成为新风险。
对策（对齐 v3.0 技术栈 §2.7）：
- token 单次有效（consume 后立即失效）
- 60s TTL（HUB_TERMINAL_TOKEN_TTL 可调）
- 通过 `Sec-WebSocket-Protocol` 子协议传递，不出现在 URL / 查询串 / 日志
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _Token:
    value: str
    purpose: str
    expires_at: float
    used: bool = False


class TerminalTokenRegistry:
    def __init__(self, ttl: float | None = None, max_tokens: int = 64) -> None:
        self.ttl = (ttl if ttl is not None else
                    float(os.environ.get("HUB_TERMINAL_TOKEN_TTL", "60")))
        self.max_tokens = max_tokens
        self._lock = threading.Lock()
        self._tokens: dict[str, _Token] = {}

    def issue(self, purpose: str = "terminal", trace_id: str = "") -> dict[str, Any]:
        with self._lock:
            self._prune()
            if len(self._tokens) >= self.max_tokens:
                oldest = min(self._tokens.values(), key=lambda t: t.expires_at)
                self._tokens.pop(oldest.value, None)
            value = secrets.token_urlsafe(32)
            self._tokens[value] = _Token(value=value, purpose=purpose,
                                         expires_at=time.time() + self.ttl)
        return {"token": value, "ttl": int(self.ttl), "purpose": purpose,
                "trace_id": trace_id}

    def consume(self, value: str, purpose: str | None = None) -> bool:
        """单次有效校验：通过即标记已用，第二次使用必定失败。"""
        with self._lock:
            self._prune()
            item = self._tokens.get(value)
            if item is None or item.used:
                return False
            if purpose and item.purpose != purpose:
                return False
            if item.expires_at < time.time():
                self._tokens.pop(value, None)
                return False
            item.used = True
            return True

    def revoke(self, value: str) -> None:
        with self._lock:
            self._tokens.pop(value, None)

    def revoke_all(self) -> None:
        with self._lock:
            self._tokens.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._tokens)

    def _prune(self) -> None:
        now = time.time()
        for key, item in list(self._tokens.items()):
            if item.expires_at < now:
                self._tokens.pop(key, None)


def parse_subprotocols(header: str | None) -> list[str]:
    """解析 `Sec-WebSocket-Protocol` 头（逗号分隔，容忍空格）。"""
    if not header:
        return []
    return [p.strip() for p in header.split(",") if p.strip()]


def pick_token(header: str | None, prefix: str) -> str:
    """从子协议列表中取出 `<prefix>.<token>` 形式的 token（不存在返回空串）。"""
    for proto in parse_subprotocols(header):
        if proto.startswith(prefix + "."):
            return proto[len(prefix) + 1:]
    return ""
