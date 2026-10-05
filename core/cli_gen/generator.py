"""CLI 反向生成（阶段 3 差异化亮点）。

把已注册的 MCP 工具反向生成为可执行的独立 CLI 脚本（python + httpx + argparse），
开发者可在 MCP 模式与 CLI 模式间无缝切换（双向能力，答辩话术见 docs/dev_log.md）。
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

_SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
"""自动生成：{name}（UniAgent Hub CLI 反向生成）。

等价于 MCP 调用 tools/call({name!r})。用法：
    python {filename} --help
"""
import argparse
import json
import os
import sys
import httpx

# Hub 地址：默认值在生成时写入，可用 HUB_URL 环境变量覆盖（换端口无需重新生成）
HUB_URL = os.environ.get("HUB_URL", {hub_url!r})
TOOL = {name!r}

def main() -> int:
    parser = argparse.ArgumentParser(description={desc!r})
{arg_help}
    args = parser.parse_args()
    # 未指定的可选参数（None）不发送，避免向网关传 null
    arguments = {{k: v for k, v in vars(args).items() if v is not None}}
    payload = {{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {{"name": TOOL, "arguments": arguments,
                          "caller": "cli_gen"}}}}
    try:
        resp = httpx.post(HUB_URL + "/mcp", json=payload, timeout=30)
        body = resp.json()
    except Exception as e:
        print(f"[错误] 连接 Hub 失败: {{e}}", file=sys.stderr)
        return 1
    result = body.get("result", {{}})
    if result.get("isError"):
        print(f"[error {{result.get('meta', {{}}).get('error_code', '?')}}] "
              f"{{result['content'][0]['text']}}", file=sys.stderr)
        return 2
    print(result["content"][0]["text"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


class CLIGenerator:
    """生成/写回 CLI 脚本到 out_dir，并输出 README。"""

    def __init__(self, hub_url: str = "http://127.0.0.1:8000",
                 out_dir: str | Path = "generated_cli") -> None:
        self.hub_url = hub_url.rstrip("/")
        self.out_dir = Path(out_dir)

    def script_text(self, tool: dict[str, Any]) -> str:
        name = tool["name"]
        schema = tool.get("inputSchema", {})
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        arg_lines: list[str] = []
        for pname, pschema in props.items():
            kw: list[str] = []
            # 统一生成为 --name 选项形式（与 README 用法示例一致）：
            # 位置参数不允许 required=True（历史缺陷：带参脚本启动即 TypeError）；
            # 选项式还避免多参数时的顺序耦合。
            if pname in required:
                kw.append("required=True")
            else:
                default = pschema.get("default")
                if default is not None:
                    kw.append(f"default={default!r}")
            # 按 Schema 类型生成转换：命令行参数默认是字符串，
            # 数字/布尔参数必须显式转换，否则网关类型校验返回 1002（历史缺陷）
            ptype = pschema.get("type", "string")
            if ptype == "boolean":
                kw.append("action='store_true'")
            elif ptype == "integer":
                kw.append("type=int")
            elif ptype == "number":
                kw.append("type=float")
            desc = pschema.get("description", "")
            kw.append(f"help={desc!r}")
            arg_lines.append(
                f"    parser.add_argument('--{pname}', {', '.join(kw)})")
        arg_help = "\n".join(arg_lines) if arg_lines else "    # 本工具无参数"
        filename = f"gen_{name}.py"

        return textwrap.dedent(_SCRIPT_TEMPLATE).format(
            name=name, hub_url=self.hub_url, filename=filename,
            desc=tool.get("description", name), arg_help=arg_help)

    def generate(self, tool: dict[str, Any]) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"gen_{tool['name']}.py"
        path.write_text(self.script_text(tool), encoding="utf-8")
        return path

    def generate_all(self, tools: list[dict[str, Any]],
                     exclude: set[str] | None = None) -> list[Path]:
        exclude = exclude or {"run_workflow"}
        paths: list[Path] = []
        for t in tools:
            if t["name"] in exclude:
                continue
            paths.append(self.generate(t))
        self._write_readme(tools)
        return paths

    def _write_readme(self, tools: list[dict[str, Any]]) -> None:
        names = [f"- `gen_{t['name']}.py`：{t['description']}" for t in tools
                 if t["name"] != "run_workflow"]
        readme = (
            "# UniAgent Hub 生成的 CLI 工具\n\n"
            "由平台反向生成（MCP Tool → CLI 脚本），与 `tools/call` 等价。\n\n"
            f"Hub 地址：`{self.hub_url}`（可用环境变量 `HUB_URL` 覆盖）\n\n"
            "## 使用\n"
            "```bash\n"
            "python gen_git_status.py --repo_path /path/to/your/repo\n"
            "```\n\n"
            "## 工具列表\n" + "\n".join(names) + "\n"
        )
        (self.out_dir / "README.md").write_text(readme, encoding="utf-8")
