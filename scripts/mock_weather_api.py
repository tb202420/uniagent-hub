"""本地 Mock 天气 API（断网降级方案，零第三方依赖）。

断网 / 公共 API 不可用时替代 open-meteo：Hub 的 REST 适配器只需把服务器地址
覆写为 http://127.0.0.1:8899（环境变量 HUB_REST_BASE_URL_OVERRIDE），
工具名 / 参数 / inputSchema / 安全管道完全不变 —— "Agent 只认识 MCP，
背后是云端 API 还是本地 mock 对它透明"这一主张由此得到实证。

用法：
    python -m scripts.mock_weather_api --port 8899
"""

from __future__ import annotations

import argparse
import json
import socketserver
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# 固定回包：彩排 / 录屏结果可复现（不做随机抖动，避免现场"数值对不上"）
TEMP_C = 26.0
WINDSPEED = 9.4


class _Server(ThreadingHTTPServer):
    """跳过 socket.getfqdn()：断网时 DNS 反查会长时间阻塞（离线演示关键）。"""

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802  (http.server 约定命名)
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json({"status": "ok", "service": "mock-weather"})
            return
        if parsed.path != "/v1/forecast":
            self._json({"error": "not found", "path": parsed.path}, status=404)
            return

        qs = parse_qs(parsed.query)
        self._json({
            "latitude": _num(qs, "latitude", 39.9042),
            "longitude": _num(qs, "longitude", 116.4074),
            "generationtime_ms": 0.12,
            "utc_offset_seconds": 28800,
            "timezone": (qs.get("timezone") or ["Asia/Shanghai"])[0],
            "timezone_abbreviation": "CST",
            "elevation": 44.0,
            "current_weather": {
                "temperature": TEMP_C,
                "windspeed": WINDSPEED,
                "winddirection": 180.0,
                "weathercode": 1,
                "is_day": 1,
                "time": time.strftime("%Y-%m-%dT%H:%M", time.localtime()),
            },
        })

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *a) -> None:
        print(f"[mock-weather] {fmt % a}", flush=True)


def _num(qs: dict, key: str, default: float) -> float:
    try:
        return float((qs.get(key) or [default])[0])
    except (TypeError, ValueError):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 Mock 天气 API（断网降级）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()

    server = _Server((args.host, args.port), Handler)
    print(f"[mock-weather] 已启动 http://{args.host}:{args.port}/v1/forecast"
          f"（固定 {TEMP_C}°C，Ctrl+C 退出）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
