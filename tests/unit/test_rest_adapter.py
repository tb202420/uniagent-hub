"""REST 适配器单元测试：SSRF 防护 / 认证脱敏 / 响应截断 / 参数映射。"""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from adapters.rest_adapter.adapter import RESTAdapter
from core.contracts import CallContext
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore

HERE = Path(__file__).resolve().parents[2]
SPEC = HERE / "adapters/rest_adapter/specs/open_meteo.yaml"


def _adapter(monkeypatch, **kwargs):
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = RESTAdapter(reg, spec_source=SPEC, **kwargs)
    adapter.discover()
    return reg, adapter


def test_discover_registers_get_weather():
    reg, _ = _adapter(None)
    tools = reg.list_tools()
    by_name = {t["name"]: t for t in tools}
    assert "get_weather" in by_name
    schema = by_name["get_weather"]["inputSchema"]
    assert "latitude" in schema["properties"]
    assert "longitude" in schema["properties"]
    assert schema["required"] == ["latitude", "longitude"]
    assert by_name["get_weather"]["annotations"]["readOnlyHint"] is True


def test_call_builds_url_and_returns(monkeypatch):
    reg, adapter = _adapter(monkeypatch)
    captured = {}

    class FakeResp:
        status_code = 200
        text = '{"temperature": 20.5}'

    def fake_request(method, url, params=None, headers=None, timeout=None,
                    follow_redirects=None, json=None):
        captured.update(method=method, url=url, params=params, headers=headers)
        return FakeResp()

    # BE-7：适配器复用连接池 Client，打桩打到实例的 request
    monkeypatch.setattr(adapter._client, "request", fake_request)
    res = adapter.call_tool("get_weather",
                            {"latitude": 39.9, "longitude": 116.4, "current_weather": True},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is True
    assert '"temperature"' in res.data
    assert captured["method"].lower() == "get"   # httpx 对方法名大小写不敏感
    assert "latitude" in captured["params"] and "longitude" in captured["params"]
    assert captured["params"]["latitude"] == 39.9


def test_ssrf_blocks_private_server():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = RESTAdapter(reg, spec_source=SPEC, base_url_override="http://127.0.0.1:8080")
    adapter.discover()
    res = adapter.call_tool("get_weather", {"latitude": 1.0, "longitude": 2.0},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is False
    assert "SSRF" in res.error_msg


def test_ssrf_blocks_private_ip_literal():
    reg = ToolRegistry(SQLiteStore(Path(tempfile.mkdtemp()) / "t.db"))
    adapter = RESTAdapter(reg, spec_source=SPEC, base_url_override="http://192.168.1.5:80")
    adapter.discover()
    res = adapter.call_tool("get_weather", {"latitude": 1.0, "longitude": 2.0},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is False
    assert "SSRF" in res.error_msg


def test_api_key_from_env_masked(monkeypatch):
    reg, adapter = _adapter(monkeypatch, api_key_env="WEATHER_KEY", auth_header="X-API-Key")
    monkeypatch.setenv("WEATHER_KEY", "secret-token-123")
    captured = {}

    class FakeResp:
        status_code = 200
        text = "{}"

    def fake_request(method, url, params=None, headers=None, timeout=None,
                    follow_redirects=None, json=None):
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(adapter._client, "request", fake_request)
    adapter.call_tool("get_weather", {"latitude": 1.0, "longitude": 2.0},
                      CallContext(trace_id="t1", caller="test"))
    assert captured["headers"].get("X-API-Key") == "secret-token-123"
    # 审计/参数中不应出现密钥
    assert "secret-token-123" not in str(reg.list_tools())


def test_response_truncated(monkeypatch):
    reg, adapter = _adapter(monkeypatch)

    class FakeResp:
        status_code = 200
        text = "x" * 1_500_000

    monkeypatch.setattr(adapter._client, "request", lambda *a, **k: FakeResp())
    res = adapter.call_tool("get_weather", {"latitude": 1.0, "longitude": 2.0},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is True
    assert "截断" in res.data


def test_http_error_mapped(monkeypatch):
    reg, adapter = _adapter(monkeypatch)

    class FakeResp:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(adapter._client, "request", lambda *a, **k: FakeResp())
    res = adapter.call_tool("get_weather", {"latitude": 1.0, "longitude": 2.0},
                            CallContext(trace_id="t1", caller="test"))
    assert res.ok is False
    assert res.error_code == 1006


# ---- requestBody（body_* 参数）→ JSON body 发送（硬件测试 2 智能插座需要）----

_BODY_SPEC = """
openapi: "3.0.0"
info:
  title: 本地智能插座
  version: "1.0.0"
servers:
  - url: http://127.0.0.1:8898
paths:
  /set:
    post:
      operationId: plug_set_power
      summary: 设置插座开关
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                power: {type: boolean}
              required: [power]
      responses:
        "200": {description: ok}
"""


def test_request_body_sent_as_json(monkeypatch, tmp_path):
    """body_* 参数应以 JSON body 发出（此前 MVP 只登记参数不发送）。"""
    spec_file = tmp_path / "plug.yaml"
    spec_file.write_text(_BODY_SPEC, encoding="utf-8")
    reg = ToolRegistry(SQLiteStore(tmp_path / "t.db"))
    adapter = RESTAdapter(reg, spec_source=spec_file,
                          allowed_private_hosts=["127.0.0.1"])
    adapter.discover()
    captured = {}

    class FakeResp:
        status_code = 200
        text = '{"power": true}'

    def fake_request(method, url, params=None, headers=None, timeout=None,
                     follow_redirects=None, json=None):
        captured.update(method=method, url=url, params=params, json=json)
        return FakeResp()

    monkeypatch.setattr(adapter._client, "request", fake_request)
    res = adapter.call_tool("plug_set_power", {"body_power": True},
                            CallContext(trace_id="t1", caller="test",
                                        permission_level="write"))
    assert res.ok is True
    assert captured["method"].lower() == "post"
    assert captured["json"] == {"power": True}   # body 字段去掉 body_ 前缀后原样发送
    assert captured["params"] == {}              # body 参数不再误入 query


# ---- BE-7：连接池复用 ----

def test_shared_client_reused_across_calls(monkeypatch):
    """同一适配器的多次调用复用同一 httpx.Client（连接池），关闭时释放。"""
    reg, adapter = _adapter(monkeypatch)
    calls = {"n": 0}

    class FakeResp:
        status_code = 200
        text = "{}"

    def fake_request(*_a, **_k):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(adapter._client, "request", fake_request)
    ctx = CallContext(trace_id="t1", caller="test")
    adapter.call_tool("get_weather", {"latitude": 1.0, "longitude": 2.0}, ctx)
    adapter.call_tool("get_weather", {"latitude": 3.0, "longitude": 4.0}, ctx)
    assert calls["n"] == 2
    adapter.on_shutdown()
    assert adapter._client.is_closed
