"""演示预热 / 就绪检查（demo_start.ps1 的最后一步，也可单独运行）。

目的：把"现场第一次调用"提前到开演前，消除三类观感问题：
1. Hub 尚未监听 → 轮询 /healthz 直到就绪（而非盲等 sleep）
2. get_weather 首次冷连接 open-meteo 约 4-5s → 预热 1-2 次写入 300s 只读缓存，
   现场工作流第 2 步即命中缓存（0ms），不会像卡死
3. 温度模拟器 / 温室模拟器 MQTT 注册是异步的 → 重试 get_temperature、
   get_soil_moisture 直到状态可用

退出码：0 = 全部就绪；1 = 有检查项失败（demo_start.ps1 据此告警）。

用法：
    python -m scripts.demo_warmup --url http://127.0.0.1:8020
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

import httpx

from agent.demo_agent import MCPClient

_BEIJING = {"latitude": 39.9042, "longitude": 116.4074, "current_weather": True}


def _wait_healthz(base: str, timeout: float) -> dict[str, Any] | None:
    """轮询 /healthz 直到 200 或超时。"""
    deadline = time.time() + timeout
    last = "未响应"
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base}/healthz", timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
            last = f"HTTP {resp.status_code}"
        except Exception as e:  # 连接被拒 / 超时 / 非 JSON
            last = type(e).__name__
        time.sleep(1.0)
    print(f"[warmup] Hub 未就绪（{timeout:.0f}s 内 /healthz 仍失败：{last}）")
    return None


def _extract_temp(res: dict) -> float | None:
    """从 get_weather 回包文本中提取 current_weather.temperature。"""
    try:
        data = json.loads(res["content"][0]["text"])
        return float(data["current_weather"]["temperature"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _call(client: MCPClient, name: str, args: dict, caller: str,
          level: str = "read") -> tuple[bool, int, str]:
    """返回 (是否成功, 延迟 ms, 展示文本)。"""
    res = client.call_tool(name, args, caller=caller, permission_level=level)
    text = res.get("content", [{}])[0].get("text", "")
    return (not res.get("isError")), res.get("meta", {}).get("latency_ms", 0), text


def main() -> int:
    parser = argparse.ArgumentParser(description="UniAgent Hub 演示预热 / 就绪检查")
    parser.add_argument("--url", default="http://127.0.0.1:8020",
                        help="Hub 服务源地址（不含 /mcp 后缀）")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="等待 /healthz 就绪的最长秒数")
    parser.add_argument("--expect-tools", type=int, default=14,
                        help="期望注册工具数（演示档 14 = 软件档 11 + 温室模拟节点 3；低于此值视为异常）")
    parser.add_argument("--temp-retry", type=int, default=15,
                        help="get_temperature 重试次数（模拟器注册为异步）")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    checks: list[tuple[str, bool, str]] = []

    # 1) Hub 健康检查
    info = _wait_healthz(base, args.timeout)
    if info is None:
        return 1
    checks.append(("Hub /healthz", True, f"status={info.get('status')}"))
    print(f"[warmup] Hub 已就绪（{base}，注册 {info.get('tools')} 个工具）")

    client = MCPClient(base, timeout=60.0)

    # 2) tools/list
    try:
        tools = client.list_tools()
        names = [t["name"] for t in tools]
    except Exception as e:
        print(f"[warmup] tools/list 失败: {type(e).__name__}: {e}")
        return 1
    ok_tools = len(tools) >= args.expect_tools
    checks.append(("tools/list", ok_tools,
                   f"{len(tools)} 个工具" + ("" if ok_tools else f"（期望 ≥{args.expect_tools}）")))
    print(f"[warmup] 工具发现：{len(tools)} 个 — {', '.join(names)}")

    # 3) get_weather 预热两次（第二次应命中 300s 缓存）
    latencies: list[int] = []
    temp: float | None = None
    for _ in range(2):
        try:
            ok, lat, text = _call(client, "get_weather", _BEIJING, "warmup")
        except Exception as e:
            ok, lat, text = False, 0, f"{type(e).__name__}: {e}"
        latencies.append(lat)
        if ok:
            temp = _extract_temp({"content": [{"text": text}]}) or temp
            checks.append(("get_weather", True, f"{lat}ms"))
        else:
            checks.append(("get_weather", False, text[:80]))
            break
        print(f"[warmup] get_weather 第 {len(latencies)} 次：{lat}ms"
              f"{'（缓存命中预期 0ms）' if len(latencies) > 1 else ''}")
    if temp is not None:
        print(f"[warmup] 天气温度读数：{temp}°C")

    # 4) get_temperature：模拟器 MQTT 注册异步，需重试
    temp_ok = False
    temp_text = ""
    for attempt in range(1, args.temp_retry + 1):
        try:
            ok, lat, temp_text = _call(client, "get_temperature", {}, "warmup")
        except Exception as e:
            ok, lat, temp_text = False, 0, f"{type(e).__name__}: {e}"
        if ok:
            temp_ok = True
            print(f"[warmup] get_temperature 就绪（第 {attempt} 次尝试，{lat}ms）：{temp_text}")
            break
        time.sleep(1.0)
    checks.append(("get_temperature", temp_ok,
                   temp_text[:60] if temp_ok else "模拟器未上报（请检查模拟器窗口）"))
    if not temp_ok:
        print(f"[warmup] get_temperature 未就绪：{temp_text}")

    # 5) get_soil_moisture：温室模拟器 MQTT 注册异步，需重试
    soil_ok = False
    soil_text = ""
    for attempt in range(1, args.temp_retry + 1):
        try:
            ok, lat, soil_text = _call(client, "get_soil_moisture", {}, "warmup")
        except Exception as e:
            ok, lat, soil_text = False, 0, f"{type(e).__name__}: {e}"
        if ok:
            soil_ok = True
            print(f"[warmup] get_soil_moisture 就绪（第 {attempt} 次尝试，{lat}ms）：{soil_text}")
            break
        time.sleep(1.0)
    checks.append(("get_soil_moisture", soil_ok,
                   soil_text[:60] if soil_ok else "温室模拟器未上报（请检查 sim_esp32 窗口）"))
    if not soil_ok:
        print(f"[warmup] get_soil_moisture 未就绪：{soil_text}")

    # 6) 汇总表
    print("\n[warmup] " + "-" * 52)
    for name, ok, detail in checks:
        print(f"[warmup] {'✓' if ok else '✗'} {name:<16} {detail}")
    print("[warmup] " + "-" * 52)
    failed = [n for n, ok, _ in checks if not ok]
    if failed:
        print(f"[warmup] 就绪检查未通过：{', '.join(failed)}")
        return 1
    print("[warmup] 全部就绪，可以开始演示（P1-P6 完成）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
