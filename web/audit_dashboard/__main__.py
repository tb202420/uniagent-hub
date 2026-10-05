"""审计 Dashboard 启动入口。

用法：
    python -m web.audit_dashboard --hub http://127.0.0.1:8000 --port 18080
可选认证：HUB_DASH_USER / HUB_DASH_PASS 环境变量
"""
from __future__ import annotations

import argparse

import uvicorn

from web.audit_dashboard.app import create_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="UniAgent Hub 审计 Dashboard")
    parser.add_argument("--hub", default="http://127.0.0.1:8000",
                        help="Hub Gateway 地址（不含 /mcp）")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--db", default="data/uniagent.db")
    args = parser.parse_args()

    app = create_dashboard(hub_url=args.hub, db_path=args.db)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
