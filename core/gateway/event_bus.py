"""Hub 事件总线（v3.0）：单连接三视图共享的事件流。

设计约束：
- 发布方来自任意线程（Gateway 线程池 / PTY 读线程 / 工作流线程），
  因此只使用 threading.Lock + queue.Queue，不依赖事件循环。
- 消费方：WebSocket `/ws/events`（实时）与 HTTP `/events?since=`（轮询兜底）。
- 事件按 seq 单调递增；ring 保留最近 N 条，断线重连后可按 since 补齐。

事件类型（kind）：
  span.start / span.end     追踪瀑布图（OTel GenAI SemConv 字段）
  tool.stage               工具调用四阶段（identified / executing / result / error）
  hitl.request / hitl.decision  HITL 审批中断与决策
  agent.token              模型输出流式增量（RAF 批处理的数据源）
  workflow / step          工作流与步骤状态（v2.0 事件流语义保留）
  terminal.output / terminal.state  交互终端字节流与会话状态
  system                   系统提示（如"已切换模拟设备"）
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any


class Subscription:
    """单个订阅者：持有独立队列，避免慢消费者阻塞广播。"""

    def __init__(self, maxsize: int = 500) -> None:
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        self.closed = False

    def drain(self) -> list[dict[str, Any]]:
        """非阻塞取出当前积压的全部事件。"""
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                return items

    def close(self) -> None:
        self.closed = True


class EventBus:
    def __init__(self, maxlen: int = 2000) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subs: list[Subscription] = []

    def publish(self, kind: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "kind": kind,
                     "ts": round(time.time(), 3), **payload}
            self._events.append(event)
            subs = list(self._subs)
        for sub in subs:
            if sub.closed:
                continue
            try:
                sub.queue.put_nowait(event)
            except queue.Full:
                # 慢消费者丢弃最旧一条后重试，保证新事件不被阻塞
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass
        return event

    def subscribe(self) -> Subscription:
        sub = Subscription()
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.close()
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def since(self, since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            items = [dict(e) for e in self._events if e["seq"] > since]
        return items[-limit:]

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in list(self._events)[-limit:]]

    def clear(self) -> None:
        """清空历史（测试与演示重置用；订阅者不受影响）。"""
        with self._lock:
            self._events.clear()
            self._seq = 0


default_bus = EventBus()
