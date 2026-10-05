"""UniAgent Hub 启动入口（阶段 2+：SQLite 持久化 + 多类型适配器 + 改进方案）。

用法：
    python main.py                                # 自研网关（默认/回退路径）
    python main.py --meta-tools                   # 渐进式工具发现（4 元工具）
    python main.py --gateway fastmcp              # FastMCP 4 协议前端（元工具暴露）
    python -m adapters.mqtt_adapter.simulator     # 起模拟设备（另一终端）
    python -m agent.demo_agent                    # 跑 Demo Agent

硬件测试档（改进方案 §7，详见 docs/hardware/hardware_test_plan.md）：
    HUB_CLI_CONFIGS / HUB_SCRIPT_CONFIGS / HUB_REST_SPECS 支持**分号分隔的多份配置**，
    例如加载系统监控 CLI 与摄像头脚本（不影响默认演示档）；
    建议同时设置 HUB_DB=data/uniagent_hardware.db 做**档位隔离**
    （避免测试注册记录持久化进演示库，导致默认档恢复出孤立工具）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from adapters.cli_adapter.adapter import CLIAdapter
from adapters.database_adapter.adapter import DatabaseAdapter
from adapters.mqtt_adapter.adapter import MQTTAdapter
from adapters.rest_adapter.adapter import RESTAdapter
from adapters.script_adapter.adapter import ScriptAdapter
from core.adapters.plugins import (
    adapter_shutdown, adapter_startup, load_adapter_plugins,
)
from core.gateway.meta_tools import MetaTools
from core.gateway.server import MCPGateway, create_app
from core.guard.audit import AuditLogger, AuditStore
from core.guard.ratelimit import RateLimiter
from core.registry.registry import ToolRegistry
from core.registry.store import SQLiteStore
from core.workflow.engine import WorkflowEngine

HERE = Path(__file__).parent


@dataclass
class HubRuntime:
    """构建完成的 Hub 运行时（自研网关与 FastMCP 前端共用）。"""

    registry: ToolRegistry
    audit: AuditLogger
    gateway: MCPGateway
    engine: WorkflowEngine
    limiter: RateLimiter
    adapters: list[tuple[str, Any]]
    app: Any = None
    mqtt_adapter: MQTTAdapter | None = None

    def shutdown(self) -> None:
        """优雅关闭：逐个调用适配器生命周期回调（on_shutdown）。"""
        for _name, adapter in self.adapters:
            adapter_shutdown(adapter)


def _load_workflows() -> dict:
    """加载工作流蓝图：默认档 + HUB_WORKFLOWS（分号分隔的附加文件）。

    硬件测试档用 HUB_WORKFLOWS="core/workflow/workflows_hardware.yaml" 追加
    security_monitor / office_auto_light 等蓝图（不影响默认演示档）。
    """
    import yaml
    workflows: dict = {}
    files = [HERE / "core/workflow/workflows.yaml"]
    extra = os.environ.get("HUB_WORKFLOWS", "").strip()
    files += [Path(p.strip()) for p in extra.split(";") if p.strip()]
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        workflows.update(data.get("workflows") or {})
    return workflows


def _config_list(env_name: str, default: Path) -> list[Path]:
    """读取分号分隔的配置路径列表（环境变量未设置时使用默认单份配置）。

    多份配置用于硬件测试档（改进方案 §7）：在不改动默认演示档的前提下，
    追加 system_monitor.yaml（CLI）、hardware_tests.yaml（脚本）、smart_plug.yaml（REST）。
    """
    raw = os.environ.get(env_name, "").strip()
    items = [Path(p.strip()) for p in raw.split(";") if p.strip()]
    return items or [default]


def build_hub(broker: str, cli_configs: list[Path],
              rest_specs: list[Path] | None = None,
              script_configs: list[Path] | None = None,
              rest_base_url: str | None = None,
              db_config: Path | None = None,
              db_path: Path | None = None,
              meta_tools: bool = False,
              plugins: bool = True) -> HubRuntime:
    # SQLite 持久化：工具 + 审计（HUB_DB 可切换到独立档位，如硬件测试库）
    store = SQLiteStore(db_path or (HERE / "data" / "uniagent.db"))
    registry = ToolRegistry(store)
    restored = registry.load_from_store()
    # 审计 JSONL 路径：HUB_AUDIT_FILE 可切换到独立档位（与 HUB_DB 配套做完整档位隔离）
    audit_file_env = os.environ.get("HUB_AUDIT_FILE", "").strip()
    audit_path = Path(audit_file_env) if audit_file_env else HERE / "data" / "audit.jsonl"
    audit = AuditLogger(AuditStore(path=audit_path, sqlite=store))
    print(f"[hub] SQLite 已恢复 {restored} 个工具注册记录")

    adapters: list[tuple[str, Any]] = []

    # CLI 适配器（YAML 注册 → subprocess 沙箱执行；支持多份配置）
    for cfg in cli_configs:
        adapter = CLIAdapter(registry, config_path=cfg)
        adapter.discover()
        adapters.append(("cli", adapter))

    # REST 适配器（OpenAPI Spec 导入 → MCP Tool；支持多份规格）
    for spec in (rest_specs or []):
        adapter = RESTAdapter(registry, spec_source=spec,
                              base_url_override=rest_base_url)
        adapter.discover()
        adapters.append(("rest", adapter))

    # 脚本适配器（Python/Shell 脚本注册执行；支持多份配置）
    for cfg in (script_configs or []):
        adapter = ScriptAdapter(registry, config_path=cfg)
        adapter.discover()
        adapters.append(("script", adapter))

    # 数据库适配器（B9，第五类适配器；默认启用，--no-db / HUB_DISABLE_DB 关闭）
    if db_config is not None:
        adapter = DatabaseAdapter(registry, config_path=db_config)
        adapter.discover()
        adapters.append(("database", adapter))

    # 工作流引擎（与网关互引：引擎经网关执行每步，Guard/审计不旁路）
    limiter = RateLimiter()
    gateway = MCPGateway(registry, audit, workflow_engine=None, rate_limiter=limiter)
    engine = WorkflowEngine(gateway)
    gateway.workflow = engine
    engine.register_workflows(_load_workflows())
    # 平台级虚拟工具统一进注册中心（A1 修复）：tools/list 与 /healthz 计数一致
    registry.register_tool("run_workflow", engine.tool_definition())
    if meta_tools:
        # 渐进式工具发现（改进方案 §3）：tools/list 仅返回 4 个元工具
        gateway.meta_tools = MetaTools(gateway)
    print(f"[hub] 工作流已加载: {list(engine.workflows.keys())}")

    # MQTT 设备适配器（自动发现 + 状态缓存 + 写操作）
    mqtt_adapter = None
    if broker:
        mqtt_adapter = MQTTAdapter(registry, broker)
        mqtt_adapter.start()
        adapters.append(("mqtt", mqtt_adapter))

    # 第三方适配器插件（entry_points 自动发现，改进方案 §4）
    if plugins:
        for result in load_adapter_plugins(registry):
            if result.loaded:
                adapters.append((f"plugin:{result.name}", result.adapter))

    # 生命周期：启动回调（幂等；MQTT 已在上面 start）
    for _name, adapter in adapters:
        adapter_startup(adapter)

    print(f"[hub] 已注册 {len(registry.list_tools())} 个工具："
          f"{[t['name'] for t in registry.list_tools()]}")
    if meta_tools:
        print("[hub] 渐进式工具发现已启用（tools/list 返回 4 个元工具）")

    app = create_app(registry, audit, workflow_engine=engine,
                     rate_limiter=limiter, gateway=gateway, adapters=adapters)
    return HubRuntime(registry=registry, audit=audit, gateway=gateway,
                      engine=engine, limiter=limiter, adapters=adapters,
                      app=app, mqtt_adapter=mqtt_adapter)


def main() -> None:
    parser = argparse.ArgumentParser(description="UniAgent Hub Gateway")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址（P0-BE-2：默认仅本机；需局域网演示时用 "
                             "--host 0.0.0.0 并设置 HUB_API_TOKEN）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--broker",
                        default=os.environ.get("HUB_MQTT_BROKER", "mqtt://broker.emqx.io:1883"),
                        help="MQTT Broker（公共 broker 便于无 Docker 联调；比赛部署用 EMQX）")
    parser.add_argument("--no-mqtt", action="store_true", help="不连接 MQTT（仅 CLI 工具）")
    parser.add_argument("--no-rest", action="store_true", help="不加载 REST 适配器")
    parser.add_argument("--no-script", action="store_true", help="不加载脚本适配器")
    parser.add_argument("--no-db", action="store_true",
                        help="不加载数据库适配器（等价环境变量 HUB_DISABLE_DB=1）")
    parser.add_argument("--meta-tools", action="store_true",
                        help="渐进式工具发现：tools/list 仅返回 4 个元工具（HUB_META_TOOLS=1）")
    parser.add_argument("--gateway", choices=("selfdev", "fastmcp"),
                        default=os.environ.get("HUB_GATEWAY", "selfdev"),
                        help="协议前端：selfdev=自研 JSON-RPC（默认/回退），fastmcp=FastMCP 4")
    parser.add_argument("--no-plugins", action="store_true",
                        help="不加载 entry_points 适配器插件")
    args = parser.parse_args()

    broker = None if args.no_mqtt else args.broker
    # 断网降级：HUB_REST_SPEC 可换 Spec 文件（兼容旧变量），
    # HUB_REST_SPECS 支持分号分隔多份规格（硬件测试档）；
    # HUB_REST_BASE_URL_OVERRIDE 可把服务器地址指向本地 mock
    # （配合 HUB_REST_ALLOWED_PRIVATE_HOSTS 放行 127.0.0.1）
    rest_spec_env = os.environ.get("HUB_REST_SPEC", "").strip()
    if rest_spec_env:
        rest_specs: list[Path] | None = [Path(rest_spec_env)]
    else:
        rest_specs = None if args.no_rest else _config_list(
            "HUB_REST_SPECS", HERE / "adapters/rest_adapter/specs/open_meteo.yaml")
    rest_base_url = os.environ.get("HUB_REST_BASE_URL_OVERRIDE", "").strip() or None
    script_configs = None if args.no_script else _config_list(
        "HUB_SCRIPT_CONFIGS", HERE / "adapters/script_adapter/configs/scripts.yaml")
    cli_configs = _config_list(
        "HUB_CLI_CONFIGS", HERE / "adapters/cli_adapter/configs/cli_tools.yaml")
    # B9：数据库适配器默认启用；--no-db 或环境变量 HUB_DISABLE_DB=1 关闭
    db_disabled = args.no_db or os.environ.get("HUB_DISABLE_DB", "").strip() in ("1", "true", "yes")
    db_cfg = None if db_disabled else HERE / "adapters/database_adapter/configs/database.yaml"
    meta_on = args.meta_tools or os.environ.get("HUB_META_TOOLS", "").strip() in ("1", "true", "yes")
    # 档位隔离：HUB_DB 可指定独立存储（硬件测试档建议 data/uniagent_hardware.db），
    # 未设置时使用默认演示库 data/uniagent.db
    db_path_env = os.environ.get("HUB_DB", "").strip()
    db_path = Path(db_path_env) if db_path_env else None

    runtime = build_hub(broker, cli_configs, rest_specs=rest_specs,
                        script_configs=script_configs, rest_base_url=rest_base_url,
                        db_config=db_cfg, db_path=db_path, meta_tools=meta_on,
                        plugins=not args.no_plugins)

    try:
        if args.gateway == "fastmcp":
            # FastMCP 4 协议前端（改进方案 §2）：协议层交给 FastMCP，
            # 执行/安全/审计仍走自研网关（回退路径 = 默认 selfdev）
            from core.gateway.fastmcp_server import (
                bearer_middleware, build_fastmcp_server,
            )
            mcp = build_fastmcp_server(runtime.gateway)
            mw = bearer_middleware()
            print("[hub] FastMCP 4 协议前端已启用（streamable-http + 4 元工具"
                  + ("，Bearer 鉴权已启用）" if mw else "）"))
            asyncio.run(mcp.run_http_async(transport="streamable-http",
                                           host=args.host, port=args.port,
                                           show_banner=False, middleware=mw))
        else:
            uvicorn.run(runtime.app, host=args.host, port=args.port, log_level="info")
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    main()