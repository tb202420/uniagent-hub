"""Demo Agent —— MCP Client（自研 JSON-RPC 2.0 / Streamable HTTP）。

演示链路：Agent → MCP Gateway → 适配器 → 资源（docs/api.md §2）。
用法：
    python -m agent.demo_agent --url http://127.0.0.1:8020
"""

from __future__ import annotations

import argparse
import os
import uuid
from typing import Any

import httpx


class MCPClient:
    """极简 MCP Client：tools/list / tools/call / server/discover。

    url 为 Hub 服务源地址（不含 /mcp 路径后缀），RPC 统一发往 /mcp。
    """

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        self.url = url
        # 网关启用 Bearer Token（HUB_API_TOKEN）时自动携带
        headers = {}
        token = os.environ.get("HUB_API_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=url, timeout=timeout,
                                    headers=headers)

    def rpc(self, method: str, params: dict[str, Any] | None = None,
            rpc_id: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if rpc_id is not None:
            payload["id"] = rpc_id
        resp = self._client.post("/mcp", json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"MCP error: {body['error']}")
        return body.get("result", {})

    def list_tools(self) -> list[dict]:
        return self.rpc("tools/list", {}, rpc_id=1).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any],
                  caller: str = "demo_agent",
                  permission_level: str = "read") -> dict:
        return self.rpc("tools/call",
                        {"name": name, "arguments": arguments,
                         "caller": caller, "trace_id": uuid.uuid4().hex[:8],
                         "permission_level": permission_level},
                        rpc_id=2)


def _fmt_result(res: dict) -> str:
    meta = res.get("meta", {})
    latency = f"{meta.get('latency_ms', 0)}ms"
    if res.get("isError"):
        return f"✗ [{meta.get('error_code')}] {res['content'][0]['text']} ({latency})"
    return f"✓ {res['content'][0]['text']} ({latency})"


def main() -> None:
    parser = argparse.ArgumentParser(description="UniAgent Hub Demo Agent")
    parser.add_argument("--url", default="http://127.0.0.1:8000",
                        help="Hub 服务源地址（不含 /mcp 后缀）")
    parser.add_argument("--repo", default=None,
                        help="git_status 参数：Git 仓库路径（默认当前工作目录）")
    parser.add_argument("--dir", default=None,
                        help="file_search 参数：搜索目录（默认当前工作目录）")
    args = parser.parse_args()
    # 可移植默认值：跟随当前工作目录（在仓库根目录运行即为演示预期行为）
    repo_arg = args.repo or os.getcwd()
    dir_arg = args.dir or os.getcwd()

    client = MCPClient(args.url)

    print("=" * 60)
    print("UniAgent Hub Demo Agent — Agent 只认识 MCP 工具")
    print("=" * 60)

    # 1. 工具发现
    tools = client.list_tools()
    print(f"\n[1] tools/list — 平台注册 {len(tools)} 个工具：")
    for t in tools:
        print(f"    - {t['name']}: {t['description']}")

    # 2. 调用 CLI 工具
    print(f"\n[2] tools/call git_status (repo={repo_arg})")
    res = client.call_tool("git_status", {"repo_path": repo_arg})
    print(f"    {_fmt_result(res)}")

    # 3. 调用脚本工具（Python 沙箱；跨平台，Windows 演示可直接运行）
    print(f"\n[3] tools/call file_summary (dir={dir_arg})")
    res = client.call_tool("file_summary", {"directory": dir_arg, "ext": "py"})
    print(f"    {_fmt_result(res)}")

    # 4. 注入攻击被拦截（CLI 工具参数在 Guard 校验阶段即被拦下，未执行）
    print("\n[4] 恶意参数注入测试：pattern='x; rm -rf /'")
    res = client.call_tool("file_search",
                           {"directory": dir_arg, "pattern": "x; rm -rf /"})
    print(f"    {_fmt_result(res)}")

    # 5. 越权调用被拒绝（能力级权限粒度：同一设备读放行 / 写拒绝）
    print("\n[5] 越权调用测试：ac_control(action='on') 以 read 权限")
    res = client.call_tool("ac_control", {"action": "on"}, permission_level="read")
    print(f"    {_fmt_result(res)}")
    print("    对比：同一设备的 get_ac_state 用 read 权限 → 放行（最小权限原则）")
    res = client.call_tool("get_ac_state", {}, permission_level="read")
    print(f"    {_fmt_result(res)}")

    # 6. 限流触发
    print("\n[6] 限流测试：连续 3 次快速调用 get_temperature（设备限速 1/s）")
    for i in range(1, 4):
        res = client.call_tool("get_temperature", {}, caller="demo_agent")
        print(f"    第 {i} 次: {_fmt_result(res)}")

    print("\n[7] 审计日志：查看 data/audit.jsonl 中的完整调用链路")


if __name__ == "__main__":
    main()
