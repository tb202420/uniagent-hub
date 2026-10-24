"""Agent 插件宿主 CLI。

    python -m agent.plugins list                       # 插件就绪状态与模型
    python -m agent.plugins run --agent script \
        --goal "土壤湿度低于30%就浇水300秒" --url http://127.0.0.1:8020
"""

from __future__ import annotations

import argparse
import json
import threading

from agent.plugins.registry import agent_statuses, load_agent_plugins


def main() -> int:
    parser = argparse.ArgumentParser(description="UniAgent Hub Agent 插件宿主")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出插件就绪状态")
    run_p = sub.add_parser("run", help="执行一条目标")
    run_p.add_argument("--agent", default="script",
                       help="插件名（script/ollama/openai-compat/第三方）")
    run_p.add_argument("--goal", required=True, help="自然语言目标")
    run_p.add_argument("--url", default="http://127.0.0.1:8020", help="Hub 地址")
    run_p.add_argument("--permission", default="read",
                       choices=("read", "write"))
    args = parser.parse_args()

    agents = load_agent_plugins()
    if args.cmd == "list":
        print(json.dumps(agent_statuses(agents), ensure_ascii=False, indent=2))
        return 0

    adapter = agents.get(args.agent)
    if adapter is None:
        print(f"未知插件: {args.agent}（可用: {sorted(agents)}）")
        return 2
    result = adapter.run(args.goal, gateway_url=args.url,
                         permission=args.permission,
                         cancel=threading.Event())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
