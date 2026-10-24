"""WebSocket 适配器（第 6 类）测试：UniSpec 注册 / 缓存读 / 写发送 / 回环集成。

回环集成用 websockets.sync.server 在本线程起真实服务端（临时端口），
验证 连接→收帧→缓存→读字段→写回显 全链路；不依赖外部网络。
"""

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("websockets")

from adapters.websocket_adapter.adapter import WebSocketAdapter
from core.contracts import CallContext
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

CONFIG = """
streams:
  - id: ws.test.telemetry
    name: 测试遥测流
    url: ws://127.0.0.1:18901
    capabilities:
      - name: get_stream_clock
        description: 读取 clock 字段
        inputSchema: {type: object, properties: {}}
        readOnly: true
        stateField: clock
      - name: get_stream_all
        description: 读取整帧（无 stateField）
        inputSchema: {type: object, properties: {}}
        readOnly: true
      - name: stream_send
        description: 发送消息
        inputSchema:
          type: object
          properties: {message: {type: string}}
          required: [message]
        readOnly: false
    constraints: {readOnly: false, permissionLevel: write, rateLimit: 10/m, timeout: 5s}
"""


def _adapter(tmp: str) -> tuple[ToolRegistry, WebSocketAdapter]:
    cfg = Path(tmp) / "ws_streams.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    reg = ToolRegistry(SQLiteStore(Path(tmp) / "t.db"))
    adapter = WebSocketAdapter(reg, config_path=cfg)
    adapter.discover()
    return reg, adapter


CTX = CallContext(trace_id="t1", caller="test")


# ---- 单元：注册与读语义（不联网）----

def test_discover_registers_unispec_v031():
    reg, adapter = _adapter(tempfile.mkdtemp())
    tools = {t["name"] for t in reg.list_tools()}
    assert {"get_stream_clock", "get_stream_all", "stream_send"} <= tools
    spec = reg.resolve("stream_send")[0]
    assert spec.type == "websocket_stream"   # v0.3.1 新类型通过 UniSpec 校验
    assert spec.protocol == "websocket"


def test_read_cached_field_and_full_frame():
    _, adapter = _adapter(tempfile.mkdtemp())
    adapter._streams["ws.test.telemetry"]["state"] = {"clock": "12:00:00Z", "temperature": 26.5}
    res = adapter.call_tool("get_stream_clock", {}, CTX)
    assert res.ok and res.data == "12:00:00Z"
    res = adapter.call_tool("get_stream_all", {}, CTX)
    assert res.ok and res.data["temperature"] == 26.5   # 无 stateField → 整帧


def test_read_without_frame_returns_1006():
    _, adapter = _adapter(tempfile.mkdtemp())
    res = adapter.call_tool("get_stream_clock", {}, CTX)
    assert res.ok is False and res.error_code == 1006


def test_write_without_connection_returns_1006():
    _, adapter = _adapter(tempfile.mkdtemp())
    res = adapter.call_tool("stream_send", {"message": "hi"}, CTX)
    assert res.ok is False and res.error_code == 1006


def test_write_sends_json_with_request_id():
    _, adapter = _adapter(tempfile.mkdtemp())
    sent: list[str] = []

    class _FakeConn:
        def send(self, payload: str) -> None:
            sent.append(payload)

    adapter._streams["ws.test.telemetry"]["conn"] = _FakeConn()
    res = adapter.call_tool("stream_send", {"message": "hello"}, CTX)
    assert res.ok and res.data["status"] == "已发送"
    payload = json.loads(sent[0])
    assert payload["message"] == "hello"
    assert payload["request_id"] == "t1"          # 写路径携带 request_id（可追溯）


def test_non_json_frame_ignored():
    _, adapter = _adapter(tempfile.mkdtemp())
    adapter._cache("ws.test.telemetry", "ping")   # 心跳文本
    assert adapter._streams["ws.test.telemetry"]["state"] is None


# ---- 集成：真实回环（sync server，本线程后台）----

def test_roundtrip_with_real_server():
    from websockets.sync.server import serve

    received: list[dict] = []

    def handler(conn):
        # 先推两帧遥测
        conn.send(json.dumps({"clock": "2026-10-24T00:00:00Z", "temperature": 25.0}))
        while True:
            try:
                msg = conn.recv(timeout=10)
            except Exception:  # noqa: BLE001
                return
            received.append(json.loads(msg if isinstance(msg, str)
                                       else msg.decode("utf-8")))
            conn.send(json.dumps({"echo": True, **received[-1]}))

    with serve(handler, "127.0.0.1", 18901) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            reg, adapter = _adapter(tempfile.mkdtemp())
            adapter.on_startup()
            # 等待后台线程完成 连接→收帧→缓存（指数退避首轮 1s 内）
            deadline = time.time() + 8
            meta = adapter._streams["ws.test.telemetry"]
            while time.time() < deadline and meta["state"] is None:
                time.sleep(0.1)
            assert meta["state"] is not None, "未在期限内收到遥测帧"
            assert meta["connected"] is True

            res = adapter.call_tool("get_stream_clock", {}, CTX)
            assert res.ok and res.data == "2026-10-24T00:00:00Z"

            res = adapter.call_tool("stream_send", {"message": "ping"}, CTX)
            assert res.ok
            deadline = time.time() + 5
            while time.time() < deadline and not received:
                time.sleep(0.05)
            assert received and received[0]["message"] == "ping"
            assert received[0]["request_id"] == "t1"
        finally:
            adapter.on_shutdown()
            server.shutdown()
