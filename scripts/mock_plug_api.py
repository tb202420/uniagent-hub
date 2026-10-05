"""本地 Mock 智能插座 API（硬件测试 2 的无硬件预演，零第三方依赖）。

在 smart_plug.yaml 声明的接口上提供与真实插座一致的语义：
    GET  /status  → {"power": false, "online": true, ...}
    POST /set     → body {"power": true|false} → 更新并返回状态
配合 `HUB_REST_ALLOWED_PRIVATE_HOSTS=127.0.0.1` 放行私有地址后，
Hub 的 REST 适配器即可把 mock 当作真插座使用（工具名/Schema/安全管道完全一致）。

用法：
    python -m scripts.mock_plug_api --port 8898
"""

from __future__ import annotations

import argparse
import json
import socketserver
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# 初始状态（与真实插座上电默认态一致：关闭但在线）
_STATE: dict = {"power": False, "online": True, "updated_at": ""}


class _Server(ThreadingHTTPServer):
    """跳过 socket.getfqdn()：无网环境由 DNS 反查造成阻塞（同 mock_weather_api）。"""

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802  (http.server 约定命名)
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json({"status": "ok", "service": "mock-plug"})
        elif path == "/status":
            self._json(dict(_STATE))
        else:
            self._json({"error": "not found", "path": path}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/set":
            self._json({"error": "not found", "path": path}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid JSON body"}, status=400)
            return
        if "power" not in payload:
            self._json({"error": "缺少必填字段: power"}, status=400)
            return
        _STATE["power"] = bool(payload["power"])
        _STATE["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[mock-plug] 状态更新: power={_STATE['power']}", flush=True)
        self._json(dict(_STATE))

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *a) -> None:
        print(f"[mock-plug] {fmt % a}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 Mock 智能插座 API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8898)
    args = parser.parse_args()

    server = _Server((args.host, args.port), Handler)
    print(f"[mock-plug] 已启动 http://{args.host}:{args.port}"
          f"（GET /status、POST /set，Ctrl+C 退出）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()