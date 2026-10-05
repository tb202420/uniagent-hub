#!/usr/bin/env python3
"""自动生成：get_weather（UniAgent Hub CLI 反向生成）。

等价于 MCP 调用 tools/call('get_weather')。用法：
    python gen_get_weather.py --help
"""
import argparse
import json
import os
import sys
import httpx

# Hub 地址：默认值在生成时写入，可用 HUB_URL 环境变量覆盖（换端口无需重新生成）
HUB_URL = os.environ.get("HUB_URL", 'http://127.0.0.1:8020')
TOOL = 'get_weather'

def main() -> int:
    parser = argparse.ArgumentParser(description='获取指定经纬度的当前天气')
    parser.add_argument('--latitude', required=True, type=float, help='')
    parser.add_argument('--longitude', required=True, type=float, help='')
    parser.add_argument('--current_weather', action='store_true', help='')
    parser.add_argument('--timezone', help='')
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
