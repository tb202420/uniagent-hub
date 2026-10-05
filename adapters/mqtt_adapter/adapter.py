"""MQTT 设备适配器：设备自动发现 + 状态缓存 + get_* 工具。

链路（docs/unispec.md §8）：
  设备上线 → 发布 UniSpec 到 uniagent/register/<id> → 适配器订阅解析注册
  设备上报 → 发布 JSON 状态到 endpoint.topic → 适配器缓存最新值
  Agent 调用 get_temperature → 返回缓存值（readOnly）
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from core.contracts import (
    CallContext, ToolResult, E_TOOL_NOT_FOUND, E_RESOURCE_UNAVAILABLE,
)
from core.registry.registry import ToolRegistry
from core.unispec.models import UniSpec

from adapters.mqtt_adapter.topics import REGISTER_PREFIX, DEVICES_PREFIX

# 注意：paho.mqtt.client 在本机导入耗时数秒，故惰性导入（在 start() 内），
# 保证 CLI-only 模式下 Hub 秒级启动。


class MQTTAdapter:
    """实现 BaseAdapter 协议（discover / list_tools / call_tool）。"""

    def __init__(self, registry: ToolRegistry, broker: str) -> None:
        self.registry = registry
        self.broker = broker
        self._states: dict[str, dict[str, Any]] = {}   # topic -> 最新 payload
        self._client: Any | None = None
        self._running = False

    # ---- 连接与发现 ----

    def start(self) -> None:
        # 规避本机 WMI 查询挂起（Win11 已移除 wmic，platform.system() 触发
        # subprocess 等待可长达 30s+）：强制 platform 走 ver 命令快速回退。
        import platform
        if hasattr(platform, "_wmi_query"):
            def _no_wmi(*_a, **_k):
                raise OSError("WMI disabled for startup speed")
            platform._wmi_query = _no_wmi

        import paho.mqtt.client as mqtt
        host, port = _parse_broker(self.broker)
        client = mqtt.Client(
            client_id=f"uniagent_hub_{id(self) & 0xFFFF:x}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )

        def on_connect(c, _ud, _flags, rc, _props):
            if rc == 0:
                print(f"[mqtt_adapter] 已连接 {self.broker}")
                # 通配订阅：注册主题 + 设备状态主题（避免在消息回调内动态 subscribe，
                # paho 回调线程内 subscribe 存在死锁/丢失风险）
                c.subscribe(f"{REGISTER_PREFIX}/+")
                c.subscribe(f"{DEVICES_PREFIX}/+/state")
            else:
                print(f"[mqtt_adapter] 连接失败 rc={rc}（5=拒绝,1=协议错误等）")

        client.on_connect = on_connect
        client.on_disconnect = lambda c, _ud, _fl, rc, _pr: print(f"[mqtt_adapter] 断开 rc={rc}")
        client.on_message = self._on_message
        # BE-6：断线自动重连的指数退避（1s→30s），公共 broker 网络抖动时
        # 避免固定间隔的重连风暴；connect_async + loop_start 的重连同样生效
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        # connect_async + loop_start：不阻塞 Hub 启动（公共 broker 网络延迟不可控）
        client.connect_async(host, port, keepalive=30)
        client.loop_start()
        self._client = client
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    # ---- 生命周期回调（改进方案 §4）----

    def on_startup(self) -> None:
        """幂等启动（build 流程可能已显式 start）。"""
        if not self._running:
            self.start()

    def on_health_check(self) -> dict:
        connected = bool(self._client and self._client.is_connected())
        return {
            "ok": connected or not self._running,
            "broker": self.broker,
            "connected": connected,
            "devices": sum(1 for s in self.registry.all_specs()
                           if s.type == "iot_device"),
            "state_topics": len(self._states),
        }

    def on_shutdown(self) -> None:
        if self._running:
            self.stop()

    def discover(self) -> list[dict]:
        """返回当前已发现的 IoT UniSpec（来自 uniagent/register 主题）。"""
        return [s.model_dump() for s in self.registry.all_specs()
                if s.type == "iot_device"]

    def list_tools(self) -> list[dict]:
        return [t for t in self.registry.list_tools()]

    # ---- MQTT 回调 ----

    def _on_message(self, _client: mqtt.Client, _ud, msg: mqtt.MQTTMessage) -> None:
        topic, payload = msg.topic, msg.payload.decode("utf-8", errors="replace")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        if topic.startswith(REGISTER_PREFIX):
            self._handle_register(data)
            return
        # 状态 topic：缓存最新值
        self._states[topic] = data

    def _handle_register(self, raw: dict) -> None:
        try:
            spec = self.registry.register(raw, adapter=self)
        except Exception as e:
            print(f"[mqtt_adapter] UniSpec 校验失败: {e}")
            return
        # 状态订阅已由连接时的通配符 uniagent/devices/+/state 覆盖，无需动态订阅
        print(f"[mqtt_adapter] 设备自动发现: {spec.id}（{spec.name}），"
              f"工具: {[c.name for c in spec.capabilities]}")

    # ---- 执行 ----

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        resolved = self.registry.resolve(name)
        if resolved is None:
            return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                              error_msg=f"工具不存在: {name}")
        spec, cap = resolved
        if not cap.readOnly and not spec.constraints.readOnly:
            return self._call_write(spec, cap, name, args, ctx)

        start = time.perf_counter()
        topic = spec.endpoint.get("topic", "")
        state = self._states.get(topic)
        if state is None:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"设备 {spec.id} 无最新状态（离线或未上报）")
        # 字段解析（UniSpec v0.2.0）：
        # 1) 显式声明 stateField → 直接采用；
        # 2) 未声明时按 "get_X" → X 推断，但仅当 X 确实是状态键（推断失败则
        #    返回完整状态对象，支持 get_ac_state 这类"整体状态查询"能力）
        field = cap.stateField
        if field is None and name.startswith("get_"):
            candidate = name[len("get_"):]
            field = candidate if candidate in state else None
        value = state.get(field) if field else state
        if value is None:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"状态中无字段 {field!r}（当前: {list(state.keys())}）")
        latency = int((time.perf_counter() - start) * 1000)
        return ToolResult(ok=True, data=value, latency_ms=latency)

    # ---- 写操作路径（ac_control 等）----

    def _call_write(self, spec, cap, name: str, args: dict, ctx: CallContext) -> ToolResult:
        """发布命令到 command_topic（qos=1），等待设备状态回执（最多 3s）。

        回执丢失时返回"命令已发送，状态未确认"（不阻塞工作流）。
        权限（permissionLevel=write）已由 Gateway Guard 先行校验。
        """
        start = time.perf_counter()
        command_topic = spec.endpoint.get("command_topic")
        state_topic = spec.endpoint.get("topic", "")
        if not command_topic or not self._client:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"设备 {spec.id} 未声明 command_topic 或未连接")

        payload = {**args, "request_id": ctx.trace_id,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            self._client.publish(command_topic, json.dumps(payload, ensure_ascii=False), qos=1)
        except Exception as e:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"命令发布失败: {e}")

        # 等待状态回执：设备将 action 反映到 state_topic
        # 判据必须区分"本次命令的回执"与"历史残留状态"——仅比对 action 时，
        # 若缓存中上次状态恰好已是目标 action（如连续两次 ac_control on），
        # 会立即返回陈旧状态（旧 request_id/ts，甚至旧的设定温度），
        # 造成"未确认本次命令却报成功"。故优先用 request_id 精确匹配。
        ack_key = args.get("action")
        last_state = self._states.get(state_topic)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            state = self._states.get(state_topic)
            if state and _ack_matches(state, ack_key, ctx.trace_id):
                latency = int((time.perf_counter() - start) * 1000)
                return ToolResult(ok=True, data=state, latency_ms=latency,
                                  error_msg="")
            last_state = state
            time.sleep(0.1)

        latency = int((time.perf_counter() - start) * 1000)
        return ToolResult(ok=True,
                          data={"status": "命令已发送，状态未确认",
                                "request_id": ctx.trace_id,
                                "last_state": last_state},
                          latency_ms=latency)


def _ack_matches(state: dict[str, Any], ack_key: Any,
                 request_id: str) -> bool:
    """回执判据：优先 request_id 精确匹配，兼容不回声 request_id 的设备。

    设备会把命令的 request_id 回写进状态（见 sim_ac.py），据此可确认
    回执确实属于本次命令；未携带 request_id 的设备退化为 action 匹配。
    """
    state_rid = state.get("request_id")
    if state_rid:
        return state_rid == request_id
    return ack_key is None or state.get("action") == ack_key


def _parse_broker(broker: str) -> tuple[str, int]:
    import re
    m = re.match(r"^mqtt://([^:/]+)(?::(\d+))?/?$", broker)
    if not m:
        raise SystemExit(f"broker 格式错误: {broker}")
    return m.group(1), int(m.group(2) or 1883)
