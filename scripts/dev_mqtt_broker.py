"""本地 MQTT Broker（开发/E2E 用，纯 Python amqtt）。

比赛正式部署使用 deploy/docker-compose.yml 的 EMQX；本脚本仅用于
无 Docker 环境下的本地联调。

用法：
    python -m scripts.dev_mqtt_broker --port 1883
"""

from __future__ import annotations

import argparse
import asyncio
import logging


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 MQTT Broker (amqtt)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    async def _run() -> None:
        from amqtt.broker import Broker
        config = {
            "listeners": {
                "default": {"type": "tcp", "bind": f"{args.host}:{args.port}"},
            },
            "sys_interval": 0,
            "auth": {"allow_anonymous": True},
        }
        broker = Broker(config)
        try:
            await broker.start()
            print(f"[broker] MQTT Broker 已启动 {args.host}:{args.port} (Ctrl+C 退出)")
            await asyncio.Event().wait()
        finally:
            await broker.shutdown()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
