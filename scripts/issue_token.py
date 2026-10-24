"""签发短期 JWT 令牌（v2.0 §3.6）。

用法：
    set HUB_JWT_SECRET=<密钥>
    python -m scripts.issue_token --caller demo --perm write --ttl 600 \
        [--tools control_pump,get_soil_moisture]

随后以 `Authorization: Bearer <token>` 访问 /mcp（HUB_AUTH_MODE=jwt 时生效）。
"""

from __future__ import annotations

import argparse
import json
import time

from core.guard.tokens import issue_token


def main() -> int:
    parser = argparse.ArgumentParser(description="签发 UniAgent Hub 短期 JWT")
    parser.add_argument("--caller", required=True, help="调用方标识（进审计 caller 字段）")
    parser.add_argument("--perm", default="read", choices=("read", "write", "admin"))
    parser.add_argument("--ttl", type=int, default=600, help="有效期秒数（默认 600=10 分钟）")
    parser.add_argument("--tools", default="", help="允许的工具名（逗号分隔；空=全部）")
    args = parser.parse_args()

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    token = issue_token(args.caller, args.perm, args.ttl, tools)
    exp_local = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + args.ttl))
    print(token)
    print(json.dumps({"caller": args.caller, "perm": args.perm,
                      "tools": tools or "全部", "expires_at": exp_local},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
