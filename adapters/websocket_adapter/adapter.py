"""WebSocket 适配器：第 6 类资源（websocket_stream，UniSpec v0.3.1）。

设计对齐 MQTT 适配器的"状态缓存"语义：
- 订阅流：后台线程连接 ws:// 服务端，JSON 帧解析后按流缓存最新一帧
- 读能力：readOnly + stateField → 取最新帧字段（无 stateField 返回整帧，
  与 MQTT get_ac_state 语义一致）；无缓存帧返回 1006
- 写能力：把参数 JSON 发送到流（sendMessage）；发送失败 1006
- 断线指数退避重连（1s→30s，同 BE-6 经验）；on_shutdown 优雅关闭

启用方式（默认**不加载**，不影响演示档 14 工具口径）：
    HUB_WS_CONFIGS=adapters/websocket_adapter/configs/websocket_streams.yaml python main.py
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from core.contracts import (
    CallContext, ToolResult, E_TOOL_NOT_FOUND, E_RESOURCE_UNAVAILABLE, E_INTERNAL,
)
from core.registry.registry import ToolRegistry

_TOP_KEY = "streams"
_RECONNECT_MIN_S = 1.0
_RECONNECT_MAX_S = 30.0


class WebSocketAdapter:
    """实现 BaseAdapter 协议（discover / list_tools / call_tool）+ 生命周期回调。"""

    def __init__(self, registry: ToolRegistry, config_path: str | Path | None = None) -> None:
        self.registry = registry
        self.config_path = Path(config_path) if config_path else None
        self._loaded_ids: set[str] = set()
        # stream_id -> {"url": str, "state": dict|None, "conn": Any, "stop": Event}
        self._streams: dict[str, dict[str, Any]] = {}
        self._threads: list[threading.Thread] = []

    # ---- 生命周期（改进方案 §4）----

    def on_startup(self) -> None:
        """为每条流启动后台消费线程（幂等）。"""
        for sid, meta in self._streams.items():
            if not meta.get("thread"):
                t = threading.Thread(target=self._consume_loop, args=(sid,),
                                     name=f"ws-adapter-{sid}", daemon=True)
                meta["thread"] = t
                meta["stop"] = threading.Event()
                t.start()

    def on_health_check(self) -> dict:
        connected = sum(1 for m in self._streams.values() if m.get("connected"))
        return {"ok": bool(self._streams), "streams": len(self._streams),
                "connected": connected}

    def on_shutdown(self) -> None:
        for meta in self._streams.values():
            stop = meta.get("stop")
            if stop:
                stop.set()
            conn = meta.get("conn")
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - 关闭期异常不阻断
                    pass

    # ---- 注册（discover）----

    def discover(self) -> list[dict]:
        """从 YAML 加载流定义为 UniSpec（websocket_stream）并注册。"""
        if self.config_path is None:
            return []
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        specs: list[dict] = []
        for entry in raw.get(_TOP_KEY, []):
            spec = self._entry_to_unispec(entry)
            self.registry.register(spec, adapter=self)
            self._loaded_ids.add(spec["id"])
            self._streams[spec["id"]] = {"url": entry["url"], "state": None,
                                         "connected": False, "conn": None,
                                         "thread": None, "stop": None}
            specs.append(spec)
        return specs

    @staticmethod
    def _entry_to_unispec(entry: dict) -> dict:
        caps = []
        for c in entry.get("capabilities", []):
            cap = {
                "name": c["name"],
                "title": c.get("title", c["name"]),
                "description": c.get("description", f"WebSocket 能力 {c['name']}"),
                "inputSchema": c.get("inputSchema", {"type": "object", "properties": {}}),
                "outputSchema": c.get("outputSchema", {}),
                "readOnly": c.get("readOnly", False),
            }
            if c.get("stateField"):
                cap["stateField"] = c["stateField"]
            caps.append(cap)
        constraints = {
            "readOnly": entry.get("readOnly", all(c.get("readOnly", False) for c in caps)),
            "permissionLevel": entry.get("permissionLevel", "read"),
            "timeout": entry.get("timeout", "10s"),
            "rateLimit": entry.get("rateLimit"),
        }
        return {
            "id": entry["id"],
            "type": "websocket_stream",
            "name": entry["name"],
            "description": entry.get("description"),
            "protocol": "websocket",
            "endpoint": {"url": entry["url"]},
            "capabilities": caps,
            "constraints": constraints,
        }

    # ---- 查询 ----

    def list_tools(self) -> list[dict]:
        return [t for t in self.registry.list_tools()]

    # ---- 消费线程 ----

    def _consume_loop(self, sid: str) -> None:
        """连接 → 收帧 → 缓存最新 JSON 帧；断线指数退避重连。"""
        from websockets.sync.client import connect  # 惰性导入（可选依赖路径）

        meta = self._streams[sid]
        url: str = meta["url"]
        delay = _RECONNECT_MIN_S
        while not meta["stop"].is_set():
            try:
                with connect(url, open_timeout=5) as conn:
                    meta["conn"] = conn
                    meta["connected"] = True
                    delay = _RECONNECT_MIN_S
                    while not meta["stop"].is_set():
                        try:
                            frame = conn.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        self._cache(sid, frame)
            except Exception as e:  # noqa: BLE001 - 网络/协议异常统一走重连
                meta["connected"] = False
                meta["conn"] = None
                if meta["stop"].is_set():
                    return
                print(f"[ws_adapter] 流 {sid} 连接中断（{type(e).__name__}），"
                      f"{delay:.0f}s 后重连")
                meta["stop"].wait(delay)
                delay = min(delay * 2, _RECONNECT_MAX_S)
        meta["connected"] = False

    def _cache(self, sid: str, frame: Any) -> None:
        try:
            text = frame.decode("utf-8", errors="replace") if isinstance(frame, bytes) else str(frame)
            self._streams[sid]["state"] = json.loads(text)
        except json.JSONDecodeError:
            return  # 非 JSON 帧忽略（流上允许心跳文本等）

    # ---- 执行 ----

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        resolved = self.registry.resolve(name)
        if resolved is None:
            return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                              error_msg=f"工具不存在: {name}")
        spec, cap = resolved
        start = time.perf_counter()

        meta = self._streams.get(spec.id)
        if meta is None:
            return ToolResult(ok=False, error_code=E_INTERNAL,
                              error_msg=f"流 {spec.id} 未在本适配器管理")

        if cap.readOnly:
            state = meta["state"]
            if state is None:
                return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                                  error_msg=f"流 {spec.id} 暂无最新帧（未连接或服务端未推送）")
            field = cap.stateField
            value = state.get(field) if field else state
            if value is None:
                return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                                  error_msg=f"最新帧中无字段 {field!r}（当前: {list(state.keys())}）")
            latency = int((time.perf_counter() - start) * 1000)
            return ToolResult(ok=True, data=value, latency_ms=latency)

        # 写能力：整包参数 JSON 发送到流
        conn = meta.get("conn")
        if conn is None:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"流 {spec.id} 未连接，无法发送")
        payload = {**args, "request_id": ctx.trace_id,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            conn.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"发送失败: {type(e).__name__}")
        latency = int((time.perf_counter() - start) * 1000)
        return ToolResult(ok=True, data={"status": "已发送", "request_id": ctx.trace_id},
                          latency_ms=latency)
