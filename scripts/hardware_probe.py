"""硬件测试调试探针（改进方案 §7 配套工具）。

三个子命令（面向硬件接入调试，全部走 Gateway Guard 管道）：

  check   就绪检查 + 硬件相关工具探测（注册情况 / 只读工具逐个实测）
  call    调用任意工具（调试设备接口；--permission write 用于写操作）
  watch   监听设备注册消息（调试新设备上线：应在 --seconds 内看到 UniSpec 摘要）

用法：
    python -m scripts.hardware_probe check --url http://127.0.0.1:8020
    python -m scripts.hardware_probe call --tool plug_set_power --args "{\\"body_power\\": true}" --permission write
    python -m scripts.hardware_probe watch --broker mqtt://127.0.0.1:1883 --seconds 30
"""

from __future__ import annotations

import argparse
import json
import platform
import sys

import httpx

from agent.demo_agent import MCPClient

# 硬件测试档预期工具（与 docs/hardware/hardware_test_plan.md 对应）
DEFAULT_EXPECT = ",".join([
    "get_system_cpu", "get_system_memory",          # 测试 4：CLI × 系统资源
    "plug_get_state", "plug_set_power",             # 测试 2：REST × 智能插座
    "get_phone_battery", "get_phone_temperature",   # 测试 3：MQTT × 手机
    "capture_image", "detect_motion",               # 测试 1：Script × USB 摄像头
])
# check 默认实测的只读工具（写操作需显式 --permission write，由 call 子命令执行）
# 注意：不含 detect_motion / capture_image —— 二者会开启摄像头取景，
# 按"硬件操作交人工"的约定不自动执行（人工用例见 docs/hardware/hardware_test_cases.md TC-12）
DEFAULT_PROBE = ",".join([
    "get_system_cpu", "get_system_memory", "plug_get_state",
    "get_phone_battery",
])


def _text(res: dict) -> str:
    return (res.get("content") or [{}])[0].get("text", "")


def cmd_check(args: argparse.Namespace) -> int:
    base = args.url.rstrip("/")
    try:
        healthz = httpx.get(f"{base}/healthz", timeout=5).json()
    except Exception as e:  # noqa: BLE001
        print(f"[probe] Hub 未就绪: {type(e).__name__}: {e}")
        return 1
    print(f"[probe] Hub /healthz: {json.dumps(healthz, ensure_ascii=False)}")

    client = MCPClient(base, timeout=60.0)
    tools = {t["name"] for t in client.list_tools()}
    expect = [n.strip() for n in args.expect.split(",") if n.strip()]
    missing = [n for n in expect if n not in tools]
    print(f"[probe] 工具注册: {len(tools)} 个 | 预期硬件工具 {len(expect)} 个，"
          f"缺失 {missing or '无'}")

    probe = [n.strip() for n in args.probe.split(",") if n.strip()] if args.probe else []
    print(f"[probe] 只读探测（{len(probe)} 个，caller=hardware_probe）：")
    all_ok = not missing
    for name in probe:
        if name not in tools:
            print(f"    - {name:<22} 未注册")
            all_ok = False
            continue
        res = client.call_tool(name, {}, caller="hardware_probe")
        ok = not res.get("isError")
        marker = "✓" if ok else "✗"
        detail = _text(res)[:70].replace("\n", " ")
        print(f"    {marker} {name:<22} {detail}")
    return 0 if all_ok else 1


def cmd_call(args: argparse.Namespace) -> int:
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as e:
        print(f"[probe] --args 不是合法 JSON: {e}")
        return 1
    client = MCPClient(args.url.rstrip("/"), timeout=60.0)
    res = client.call_tool(args.tool, arguments, caller="hardware_probe",
                           permission_level=args.permission)
    ok = not res.get("isError")
    print(f"[probe] {args.tool}({'✓' if ok else '✗'}): {_text(res)}")
    return 0 if ok else 2


def cmd_watch(args: argparse.Namespace) -> int:
    """监听 register topic（新设备上线调试）。"""
    import re
    import time

    # 规避本机 WMI 查询挂起（同 simulator.py：导入 paho 前替换 platform 内部实现）
    if hasattr(platform, "_wmi_query"):
        def _no_wmi(*_a, **_k):
            raise OSError("WMI disabled for startup speed")
        platform._wmi_query = _no_wmi
    import paho.mqtt.client as mqtt

    from adapters.mqtt_adapter.topics import REGISTER_PREFIX

    m = re.match(r"^mqtt://([^:/]+)(?::(\d+))?/?$", args.broker)
    if not m:
        print(f"[probe] broker 格式错误: {args.broker}")
        return 1
    host, port = m.group(1), int(m.group(2) or 1883)
    seen: list[str] = []

    client = mqtt.Client(client_id="hardware_probe",
                         callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, _ud, _flags, rc, _props):
        if rc == 0:
            c.subscribe(f"{REGISTER_PREFIX}/+")
            print(f"[probe] 已连接 {args.broker}，监听 {REGISTER_PREFIX}/+ "
                  f"（{args.seconds:.0f}s）…")

    def on_message(_c, _ud, msg):
        # 本地 amqtt broker（离线档）通配订阅会额外投递 retained 状态消息，
        # 这里按 topic 前缀过滤，只处理真正的注册消息（EMQX/公共 broker 无此现象）
        if not msg.topic.startswith(REGISTER_PREFIX + "/"):
            return
        try:
            spec = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            print(f"[probe] 收到非 JSON 注册消息: {msg.topic}")
            return
        if not isinstance(spec, dict) or not spec.get("id"):
            return
        caps = [c.get("name") for c in (spec.get("capabilities") or [])]
        line = (f"[probe] 设备注册: {spec.get('id')}（{spec.get('name')}）"
                f" 能力: {caps}")
        print(line)
        seen.append(str(spec.get("id")))

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=30)
    client.loop_start()
    time.sleep(args.seconds)
    client.loop_stop()
    client.disconnect()
    print(f"[probe] 监听结束：收到 {len(seen)} 个设备注册"
          f"{'（' + ', '.join(seen) + '）' if seen else '（未收到——检查设备是否在运行）'}")
    return 0 if seen else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="UniAgent Hub 硬件测试调试探针")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="就绪检查 + 硬件工具探测")
    p_check.add_argument("--url", default="http://127.0.0.1:8020")
    p_check.add_argument("--expect", default=DEFAULT_EXPECT,
                         help="预期注册的硬件工具（逗号分隔）")
    p_check.add_argument("--probe", default=DEFAULT_PROBE,
                         help="要实测调用的只读工具（逗号分隔；空串跳过）")
    p_check.set_defaults(func=cmd_check)

    p_call = sub.add_parser("call", help="调用工具（调试设备接口）")
    p_call.add_argument("--url", default="http://127.0.0.1:8020")
    p_call.add_argument("--tool", required=True)
    p_call.add_argument("--args", default="{}", help="JSON 参数，如 '{\"power\": true}'")
    p_call.add_argument("--permission", default="read", choices=["read", "write", "admin"])
    p_call.set_defaults(func=cmd_call)

    p_watch = sub.add_parser("watch", help="监听设备注册消息")
    p_watch.add_argument("--broker", default="mqtt://127.0.0.1:1883")
    p_watch.add_argument("--seconds", type=float, default=30.0)
    p_watch.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())