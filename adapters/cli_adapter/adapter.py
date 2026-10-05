"""CLI 适配器：YAML 注册 → UniSpec → Schema 自动生成 → argv 沙箱执行。

安全约束（docs/unispec.md §7 / api.md）：
- 禁止 shell=True 与字符串拼接，一律 subprocess(argv, shell=False)
- 参数先经 Guard 校验（类型/必填/白名单正则），再拼装 argv
- allowed_commands 白名单（若声明则校验首个程序）
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from adapters.cli_adapter.template import generate_schema, parse_template, build_argv
from core.contracts import (
    CallContext, ToolResult, E_TOOL_NOT_FOUND, E_INVALID_ARGS,
    E_TIMEOUT, E_INJECTION_BLOCKED, E_INTERNAL,
)
from core.guard.validation import validate_args, DEFAULT_ARG_PATTERN
from core.registry.registry import ToolRegistry
from core.unispec.models import UniSpec

_CONFIG_TOP_KEY = "cli_tools"
# A3 修复：宿主操作系统 → platforms 模板键名
_HOST_PLATFORM_KEY = {"win32": "windows", "linux": "linux", "darwin": "darwin"}


class CLIAdapter:
    """实现 BaseAdapter 协议（discover / list_tools / call_tool）。"""

    def __init__(self, registry: ToolRegistry, config_path: str | Path | None = None) -> None:
        self.registry = registry
        self.config_path = Path(config_path) if config_path else None
        self._loaded_ids: set[str] = set()

    # ---- 生命周期回调（改进方案 §4，可选实现）----

    def on_health_check(self) -> dict:
        return {"ok": True, "config": str(self.config_path or ""),
                "tools": len(self._loaded_ids)}

    # ---- 注册（discover）----

    def discover(self) -> list[dict]:
        """从 YAML 配置加载 CLI 工具为 UniSpec 并注册。返回原始 UniSpec dict 列表。"""
        if self.config_path is None:
            return []
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        specs: list[dict] = []
        for entry in raw.get(_CONFIG_TOP_KEY, []):
            spec = self._entry_to_unispec(self._resolve_platform(entry))
            self.registry.register(spec, adapter=self)
            self._loaded_ids.add(spec["id"])
            specs.append(spec)
        return specs

    @staticmethod
    def _resolve_platform(entry: dict) -> dict:
        """按宿主操作系统选择命令模板（A3 修复：Windows 用 where，Linux 用 find）。

        entry.platforms = {linux: {...}, windows: {...}}：条目内的键
        （command/param_patterns/allowed_commands/description）覆盖顶层同名键；
        宿主平台无对应模板时回退顶层 command（供平台无关工具如 git_status）。
        """
        platforms = entry.get("platforms")
        if not platforms:
            return entry
        chosen = platforms.get(_HOST_PLATFORM_KEY.get(sys.platform, ""))
        if not chosen:
            if "command" in entry:  # 平台无关工具：顶层 command 兜底
                return entry
            raise ValueError(
                f"CLI 工具 {entry.get('id')}: 当前平台（{sys.platform}）无模板，"
                f"可用: {sorted(platforms)}")
        merged = {**entry, **chosen}
        merged.pop("platforms", None)
        return merged

    @staticmethod
    def _entry_to_unispec(entry: dict) -> dict:
        """YAML 条目 → UniSpec dict（docs/unispec.md §6.2 结构）。"""
        command: str = entry["command"]
        tool_name: str = entry.get("tool_name") or entry["id"].rsplit(".", 1)[-1].replace("-", "_")
        schema = generate_schema(command)

        # 注入防护：为字符串参数注入白名单（条目级 param_patterns 可覆盖）
        for arg_name, prop in schema.get("properties", {}).items():
            if prop.get("type") == "string" and "pattern" not in prop:
                prop["pattern"] = entry.get("param_patterns", {}).get(arg_name, DEFAULT_ARG_PATTERN)

        cap = {
            "name": tool_name,
            "title": entry.get("title", entry["name"]),
            "description": entry.get("description", f"执行命令: {command}"),
            "command": command,
            "inputSchema": schema,
            "outputSchema": {"type": "string"},
            "readOnly": entry.get("readOnly", False),
        }
        constraints = {
            "readOnly": entry.get("readOnly", False),
            "permissionLevel": entry.get("permissionLevel", "read"),
            "timeout": entry.get("timeout", "10s"),
            "allowedPaths": entry.get("allowedPaths", []),
            "allowedCommands": entry.get("allowed_commands", []),
        }
        return {
            "id": entry["id"],
            "type": "cli_tool",
            "name": entry["name"],
            "description": entry.get("description"),
            "protocol": "subprocess",
            "endpoint": {},
            "capabilities": [cap],
            "constraints": constraints,
        }

    # ---- 查询（list_tools）----

    def list_tools(self) -> list[dict]:
        return [t for t in self.registry.list_tools()]

    # ---- 执行（call_tool）----

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        resolved = self.registry.resolve(name)
        if resolved is None:
            return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                              error_msg=f"工具不存在: {name}")
        spec, cap = resolved
        start = time.perf_counter()

        # 1) Guard 参数校验（类型 / 必填 / 白名单注入防护）
        #    路径类参数统一规范化：Windows 反斜杠 → 正斜杠，规避正则转义陷阱
        norm_args = {k: (v.replace("\\", "/") if isinstance(v, str) else v)
                     for k, v in (args or {}).items()}
        errors = validate_args(cap.inputSchema, norm_args, cap.paramPatterns)
        if errors:
            return ToolResult(ok=False, error_code=E_INJECTION_BLOCKED if
                              any("注入防护" in e or "非法字符" in e for e in errors) else E_INVALID_ARGS,
                              error_msg="; ".join(errors))

        # 2) 命令白名单
        allowed = spec.constraints.allowedCommands
        elements, _ = parse_template(cap.command)
        program = ""
        if elements and elements[0]:
            first = elements[0][0]
            program = first.literal or ""
        if allowed and program and program not in allowed:
            return ToolResult(ok=False, error_code=E_INJECTION_BLOCKED,
                              error_msg=f"程序 {program!r} 不在 allowed_commands 白名单 {allowed} 中")

        # 3) argv 拼装 + subprocess 沙箱执行（shell=False）
        try:
            argv = build_argv(elements, norm_args)
        except KeyError as e:
            return ToolResult(ok=False, error_code=E_INVALID_ARGS,
                              error_msg=f"缺少参数: {e}")
        except Exception as e:  # 拼装异常（注入防护兜底）
            return ToolResult(ok=False, error_code=E_INJECTION_BLOCKED,
                              error_msg=f"argv 拼装失败（注入防护拦截）: {e}")

        try:
            # 子进程输出编码不可控（GBK/UTF-8 混杂），errors="replace" 保证
            # stdout/stderr 恒为字符串，不因解码失败在 reader 线程抛异常
            proc = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=spec.constraints.timeout_seconds(),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error_code=E_TIMEOUT,
                              error_msg=f"命令执行超时（{spec.constraints.timeout}）")
        except FileNotFoundError:
            return ToolResult(ok=False, error_code=E_RESOURCE_UNAVAILABLE,
                              error_msg=f"程序不存在: {argv[0]}")
        except Exception as e:
            return ToolResult(ok=False, error_code=E_INTERNAL, error_msg=f"执行失败: {e}")

        latency = int((time.perf_counter() - start) * 1000)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            return ToolResult(ok=False, error_code=E_INTERNAL,
                              error_msg=f"命令退出码 {proc.returncode}: {stderr[:500]}",
                              latency_ms=latency)
        output = (proc.stdout or "").strip()
        return ToolResult(ok=True, data=output, latency_ms=latency)
