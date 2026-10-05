#!/usr/bin/env python3
"""自动生成：db_execute（UniAgent Hub CLI 反向生成）。

等价于 MCP 调用 tools/call('db_execute')。用法：
    python gen_db_execute.py --help
"""
import argparse
import json
import os
import sys
import httpx

# Hub 地址：默认值在生成时写入，可用 HUB_URL 环境变量覆盖（换端口无需重新生成）
HUB_URL = os.environ.get("HUB_URL", 'http://127.0.0.1:8020')
TOOL = 'db_execute'

def main() -> int:
    parser = argparse.ArgumentParser(description='对演示数据库执行受限写操作（INSERT/UPDATE/DELETE 单语句，需 write 权限）')
    parser.add_argument('--sql', required=True, help='SQL 单语句（无分号/注释）')
    args = parser.parse_args()
    # 未指定的可选参数（None）不发送，避免向网关传 null
    arguments = {k: v for k, v in vars(args).items() if v is not None}
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": TOOL, "arguments": arguments,
                          "caller": "cli_gen"}}
    try:
        resp = httpx.post(HUB_URL + "/mcp", json=payload, timeout=30)
        body = resp.json()
    except Exception as e:
        print(f"[错误] 连接 Hub 失败: {e}", file=sys.stderr)
        return 1
    result = body.get("result", {})
    if result.get("isError"):
        print(f"[error {result.get('meta', {}).get('error_code', '?')}] "
              f"{result['content'][0]['text']}", file=sys.stderr)
        return 2
    print(result["content"][0]["text"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
