"""演示用 WebSocket 遥测流服务端（配合第 6 类适配器本地联调，不影响默认演示档）。

行为：
- 周期（默认 2s）向所有客户端广播 JSON 帧：{"clock": <UTC>, "temperature": <模拟值>}
- 回显客户端发来的任何 JSON 消息（追加 echo=true），验证 stream_send 写路径

用法：
    python -m scripts.dev_ws_stream --port 8765
然后（另一终端，显式启用 WebSocket 适配器）：
    set HUB_WS_CONFIGS=adapters/websocket_adapter/configs/websocket_streams.yaml
    python main.py --no-mqtt --port 8020
"""

from __future__ import annotations

import argparse
import json
import random
import time
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="演示 WebSocket 遥测流服务端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    from websockets.sync.server import serve

    def handler(conn: Any) -> None:
        peer = getattr(conn, "remote_address", None)
        print(f"[ws_stream] 客户端接入: {peer}")
        try:
            while True:
                # 发送侧：周期遥测帧
                frame = {"clock": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "temperature": round(random.uniform(24.0, 30.0), 1)}
                try:
                    conn.send(json.dumps(frame, ensure_ascii=False))
                except Exception:  # noqa: BLE001 - 对端断开
                    return
                try:
                    msg = conn.recv(timeout=args.interval)
                except TimeoutError:
                    continue
                # 收到写消息 → 回显（验证 stream_send）
                try:
                    data = json.loads(msg if isinstance(msg, str)
                                      else msg.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    data = {"raw": str(msg)[:100]}
                data["echo"] = True
                conn.send(json.dumps(data, ensure_ascii=False))
                print(f"[ws_stream] 回显: {data}")
        except Exception:  # noqa: BLE001 - 连接级异常，结束该连接
            pass
        finally:
            print(f"[ws_stream] 客户端断开: {peer}")

    with serve(handler, args.host, args.port) as server:
        print(f"[ws_stream] 遥测流服务端已启动 ws://{args.host}:{args.port}"
              f"（周期 {args.interval}s 推送 clock/temperature）")
        server.serve_forever()


if __name__ == "__main__":
    main()
