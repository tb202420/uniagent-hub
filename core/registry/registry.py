"""工具注册中心（ToolRegistry）—— SQLite 持久化版（阶段 2）。

职责：注册/注销 UniSpec（内存缓存 + SQLite 落盘）、按工具名解析到
（UniSpec, Capability）、合并输出 MCP tools/list、重启后从库恢复。
"""

from __future__ import annotations

from typing import Any

from core.registry.store import SQLiteStore
from core.unispec.models import Capability, UniSpec


class ToolRegistry:
    def __init__(self, store: SQLiteStore | None = None) -> None:
        self._specs: dict[str, UniSpec] = {}          # uniagent resource id -> UniSpec
        self._tools: dict[str, tuple[UniSpec, Capability]] = {}  # capability name -> (spec, cap)
        self._owners: dict[str, Any] = {}             # resource id -> 负责的适配器
        self._extra_tools: dict[str, dict[str, Any]] = {}  # 平台级虚拟工具（如 run_workflow）
        self.store = store

    # ---- 注册 / 注销 ----

    def register(self, spec: UniSpec | dict[str, Any], adapter: Any = None) -> UniSpec:
        """注册一个 UniSpec（接受模型实例或原始 dict，dict 会先校验）。"""
        model = spec if isinstance(spec, UniSpec) else UniSpec.model_validate(spec)
        self._specs[model.id] = model
        if adapter is not None:
            self._owners[model.id] = adapter
        for cap in model.capabilities:
            self._tools[cap.name] = (model, cap)
        if self.store is not None:
            self.store.upsert_spec(model.model_dump())
        return model

    def register_many(self, specs: list[UniSpec | dict[str, Any]]) -> list[UniSpec]:
        return [self.register(s) for s in specs]

    def register_tool(self, name: str, definition: dict[str, Any]) -> None:
        """注册平台级虚拟工具（MCP Tool 定义，非 UniSpec 资源型工具）。

        run_workflow 等由基础设施层（WorkflowEngine）提供的工具走此通道：
        只存活于内存、不落库 —— 每次启动由 build 流程重建，避免与
        UniSpec 的 type 枚举（冻结契约）混用。list_tools() 统一合并输出，
        使注册中心成为 tools/list 与 /healthz 计数的唯一事实来源。
        """
        self._extra_tools[name] = definition

    def unregister(self, resource_id: str) -> bool:
        spec = self._specs.pop(resource_id, None)
        if spec is None:
            return False
        for cap in spec.capabilities:
            self._tools.pop(cap.name, None)
        self._owners.pop(resource_id, None)
        if self.store is not None:
            self.store.delete_spec(resource_id)
        return True

    # ---- 持久化恢复 ----

    def load_from_store(self) -> int:
        """启动时从 SQLite 恢复工具（适配器归属随后由各适配器 discover() 重建）。"""
        if self.store is None:
            return 0
        count = 0
        for raw in self.store.load_all_specs():
            try:
                model = UniSpec.model_validate(raw)
            except Exception:
                continue  # 损坏记录跳过
            self._specs[model.id] = model
            for cap in model.capabilities:
                self._tools.setdefault(cap.name, (model, cap))
            count += 1
        return count

    # ---- 查询 ----

    def get(self, resource_id: str) -> UniSpec | None:
        return self._specs.get(resource_id)

    def resolve(self, tool_name: str) -> tuple[UniSpec, Capability] | None:
        """按 MCP Tool 名解析到所属 UniSpec 与 Capability。"""
        return self._tools.get(tool_name)

    def owner_of(self, resource_id: str) -> Any | None:
        """返回负责该资源的适配器（用于 Gateway 路由）。"""
        return self._owners.get(resource_id)

    def list_tools(self) -> list[dict[str, Any]]:
        """合并全部资源 + 平台级虚拟工具的 MCP Tool 定义（tools/list 响应）。"""
        tools: list[dict[str, Any]] = []
        for spec in self._specs.values():
            tools.extend(spec.mcp_tools())
        tools.extend(self._extra_tools.values())
        return tools

    def all_specs(self) -> list[UniSpec]:
        return list(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)
