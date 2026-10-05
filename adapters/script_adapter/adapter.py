"""脚本适配器：Python/Shell 脚本注册与执行（阶段 2）。

设计（答辩要点）：不做进程内 exec，而是复用 CLI 适配器的 subprocess 沙箱：
- argv 数组执行（shell=False），参数经 Gateway Guard 横切校验
- 脚本文件路径白名单：entry 必须位于 scripts_root 之下，禁止 ../ 逃逸
- 脚本 stdout 输出 JSON，适配器解析后结构化返回
- 工作目录固定为 scripts_root
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from adapters.cli_adapter.template import generate_schema, parse_template, build_argv
from core.contracts import (
    CallContext, ToolResult,
    E_TOOL_NOT_FOUND, E_INVALID_ARGS, E_INJECTION_BLOCKED, E_TIMEOUT, E_INTERNAL,
)
from core.registry.registry import ToolRegistry

_TOP_KEY = "scripts"


class ScriptAdapter:
    """实现 BaseAdapter 协议（discover / list_tools / call_tool）。"""

    def __init__(self, registry: ToolRegistry, config_path: str | Path,
                 scripts_root: str | Path | None = None) -> None:
        self.registry = registry
        self.config_path = Path(config_path)
        # 默认脚本目录 = 适配器包内 scripts/（与 configs/ 平级）
        self.scripts_root = Path(scripts_root) if scripts_root \
            else Path(__file__).resolve().parent / "scripts"

    # ---- 生命周期回调（改进方案 §4，可选实现）----

    def on_health_check(self) -> dict:
        return {"ok": self.scripts_root.exists(),
                "scripts_root": str(self.scripts_root)}

    # ---- 注册（discover）----

    def discover(self) -> list[dict]:
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        specs: list[dict] = []
        for entry in raw.get(_TOP_KEY, []):
            spec = self._entry_to_unispec(entry)
            if spec is None:
                continue
            self.registry.register(spec, adapter=self)
            specs.append(spec)
        return specs

    def _entry_to_unispec(self, entry: dict) -> dict | None:
        entry_path = entry.get("entry", "")
        runtime = entry.get("runtime", "python")
        args_template = entry.get("args_template", "")
        schema = generate_schema(args_template)
        tool_name = entry.get("tool_name") or entry["id"].rsplit(".", 1)[-1].replace("-", "_")

        # 脚本路径白名单：entry 必须位于 scripts_root 之下（拒绝 ../ 逃逸）
        full = (self.scripts_root / entry_path).resolve()
        if not full.is_relative_to(self.scripts_root.resolve()):
            print(f"[script_adapter] 拒绝注册: entry 超出 scripts_root: {entry_path}")
            return None
        if not full.exists():
            print(f"[script_adapter] 拒绝注册: 脚本不存在: {full}")
            return None

        return {
            "id": entry["id"],
            "type": "local_script",
            "name": entry.get("name", entry["id"]),
            "description": entry.get("description", f"执行脚本 {entry_path}"),
            "protocol": "script",
            "endpoint": {"path": str(full), "interpreter": runtime},
            "capabilities": [{
                "name": tool_name,
                "title": tool_name,
                "description": entry.get("description", f"执行脚本 {entry_path}"),
                "command": args_template,
                "inputSchema": schema,
                "outputSchema": {"type": "object"},
                "readOnly": entry.get("readOnly", False),
            }],
            "constraints": {
                "readOnly": entry.get("readOnly", False),
                "permissionLevel": entry.get("permissionLevel", "read"),
                "timeout": entry.get("timeout", "10s"),
                "allowedPaths": [str(self.scripts_root.resolve())],
            },
        }

    # ---- 查询 ----

    def list_tools(self) -> list[dict]:
        return [t for t in self.registry.list_tools()]

    # ---- 执行 ----

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        resolved = self.registry.resolve(name)
        if resolved is None:
            return ToolResult(ok=False, error_code=E_TOOL_NOT_FOUND,
                              error_msg=f"工具不存在: {name}")
        spec, cap = resolved
        start = time.perf_counter()

        # 路径白名单复核（纵深防御）：endpoint.path 必须在 scripts_root 下
        root = self.scripts_root.resolve()
        ep_path = Path(spec.endpoint.get("path", ""))
        try:
            ep_resolved = ep_path.resolve()
        except OSError:
            return ToolResult(ok=False, error_code=E_INJECTION_BLOCKED,
                              error_msg="脚本路径解析失败（路径白名单拦截）")
        if not ep_resolved.is_relative_to(root):
            return ToolResult(ok=False, error_code=E_INJECTION_BLOCKED,
                              error_msg=f"脚本路径超出白名单: {ep_resolved}")

        elements, _ = parse_template(cap.command or "")
        try:
            argv = build_argv(elements, args)
        except KeyError as e:
            return ToolResult(ok=False, error_code=E_INVALID_ARGS, error_msg=f"缺少参数: {e}")
        interpreter = spec.endpoint.get("interpreter", "python")
        cmd = [interpreter, str(ep_resolved), *argv]

        try:
            # 子进程是平台自带 Python 脚本：显式 UTF-8 管道——经 PYTHONIOENCODING
            # 让子进程以 UTF-8 编码输出、父进程按 UTF-8 解码，避免宿主 locale
            # （如 Windows runner 的 cp1252）下 print 中文即 UnicodeEncodeError
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(
                cmd, shell=False, capture_output=True,
                encoding="utf-8", errors="replace", env=child_env,
                timeout=spec.constraints.timeout_seconds(), cwd=str(root),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error_code=E_TIMEOUT,
                              error_msg=f"脚本执行超时（{spec.constraints.timeout}）")
        except FileNotFoundError:
            return ToolResult(ok=False, error_code=E_INTERNAL,
                              error_msg=f"解释器不存在: {interpreter}")
        except Exception as e:
            return ToolResult(ok=False, error_code=E_INTERNAL, error_msg=f"执行失败: {e}")

        latency = int((time.perf_counter() - start) * 1000)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            return ToolResult(ok=False, error_code=E_INTERNAL,
                              error_msg=f"脚本退出码 {proc.returncode}: {stderr[:300]}",
                              latency_ms=latency)
        out = (proc.stdout or "").strip()
        try:
            return ToolResult(ok=True, data=json.loads(out), latency_ms=latency)
        except json.JSONDecodeError:
            return ToolResult(ok=True, data=out, latency_ms=latency)
