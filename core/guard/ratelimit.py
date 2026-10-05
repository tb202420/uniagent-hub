"""Guard v2 限流器：滑动窗口，按 (tool, caller) 维度（答辩安全亮点）。

配合 UniSpec constraints.rateLimit（格式 "5/m" "100/h"）在 Gateway Guard 管道中拦截，
超限返回 1004（E_RATE_LIMITED，docs/api.md §4 冻结契约）。
"""

from __future__ import annotations

import re
import threading
import time

_RATE_RE = re.compile(r"^(\d+)/(s|m|h|d)$")
_WINDOW = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def parse(rate_limit: str) -> tuple[int, float] | None:
        """'5/m' -> (5, 60.0)。非法返回 None。"""
        m = _RATE_RE.match(rate_limit)
        if not m:
            return None
        return int(m.group(1)), _WINDOW[m.group(2)]

    def check(self, tool: str, caller: str, rate_limit: str,
              scope: str = "external") -> bool:
        """True=放行，False=超限（滑动窗口）。

        scope：限流桶维度隔离——外部调用与工作流内调用互不挤占
        （工作流内以 wf:<trace_id> 单独计数，防误伤）。
        """
        parsed = self.parse(rate_limit)
        if parsed is None:
            return True  # 未声明/非法限流 → 放行
        limit, window = parsed
        key = (tool, caller, scope)
        now = time.monotonic()
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if now - t < window]
            if len(bucket) >= limit:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            return True

    def reset(self, tool: str | None = None, caller: str | None = None) -> int:
        """清空计数（测试用）。返回清除条数。"""
        with self._lock:
            if tool is None:
                n = len(self._hits)
                self._hits.clear()
                return n
            keys = [k for k in self._hits if k[0] == tool and (caller is None or k[1] == caller)]
            for k in keys:
                self._hits.pop(k, None)
            return len(keys)
