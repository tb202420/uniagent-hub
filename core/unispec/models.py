"""UniSpec v0.4.0 — 统一能力描述规范（契约见 docs/unispec.md）。

Pydantic 模型 + 校验。所有适配器与注册中心共享此模型。
v0.2.0 新增 capability 扩展字段：stateField / paramPatterns / permissionLevel。
v0.4.0（v3.0 批次）新增协议绑定字段：version / protocol_bindings /
control_mechanisms / self_description（均为可选，向后兼容 v0.3.x 描述）。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---- 枚举约束（与 docs/unispec.md §9 保持一致）----

# v0.3.0（B9 修复批次）新增 "database"/"sqlite"：第五类资源（数据库）
# v0.3.1（2026-10-24，第 6 类适配器批次）新增 "websocket_stream"/"websocket"：WebSocket 流资源（增量扩展，向后兼容）
ResourceType = Literal["iot_device", "cli_tool", "rest_api", "local_script", "database", "websocket_stream"]
ProtocolType = Literal["mqtt", "http", "subprocess", "script", "stdio", "sqlite", "websocket"]
PermissionLevel = Literal["read", "write", "admin"]
# v0.4.0 协议绑定（AGI 协议栈三层显式映射）
HardwareSide = Literal["MHS-compatible", "none"]
AgentAccess = Literal["mcp"]
InterAgent = Literal["a2a"]
ControlMechanism = Literal["mcp_tool", "cli", "code_file"]

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_CAP_NAME_PATTERN = re.compile(r"^[a-z][a-zA-Z0-9_]*$")
_RATELIMIT_PATTERN = re.compile(r"^\d+/(s|m|h|d)$")
_TIMEOUT_PATTERN = re.compile(r"^\d+(ms|s|m)$")

# 默认参数白名单：禁止 shell 元字符，防止命令注入。
# 允许字母数字、下划线、点、斜杠、冒号、短横线、空格、星号（glob）。
_DEFAULT_ARG_PATTERN = r"^[a-zA-Z0-9_/.:\- *]+$"


class Capability(BaseModel):
    """能力项 —— 1:1 映射为一个 MCP Tool。"""

    name: str = Field(description="camelCase 工具名，即 MCP Tool 名")
    title: str | None = None
    description: str
    command: str | None = Field(default=None, description="CLI 模板命令，含 {placeholder}")
    http: dict[str, Any] | None = Field(default=None, description="REST 方法/路径信息")
    inputSchema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    readOnly: bool = False
    rateLimit: str | None = None
    # 参数白名单（注入防护）：参数名 -> 允许的正则。缺省时用 _DEFAULT_ARG_PATTERN
    paramPatterns: dict[str, str] = Field(default_factory=dict)
    # 扩展字段（UniSpec v0.2.0）：IoT 状态映射 —— 从 MQTT 状态 payload 中取该字段作为输出
    stateField: str | None = None
    # 扩展字段（UniSpec v0.2.0）：能力级权限覆盖。
    # 优先级：cap.permissionLevel > (readOnly ? "read" : spec.constraints.permissionLevel)
    # 向后兼容：未设置时 readOnly 能力自动降为 read（最小权限），写能力沿用资源级声明
    permissionLevel: PermissionLevel | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _CAP_NAME_PATTERN.match(v):
            raise ValueError(f"capability.name 非法: {v!r}（需匹配 {_CAP_NAME_PATTERN.pattern}）")
        return v

    @field_validator("rateLimit")
    @classmethod
    def _check_rate_limit(cls, v: str | None) -> str | None:
        if v is not None and not _RATELIMIT_PATTERN.match(v):
            raise ValueError(f"rateLimit 非法: {v!r}（格式如 10/s、1/m）")
        return v


class Constraints(BaseModel):
    """资源级约束声明。"""

    readOnly: bool = False
    permissionLevel: PermissionLevel = "read"
    rateLimit: str | None = None
    timeout: str = "10s"
    allowedPaths: list[str] = Field(default_factory=list)
    allowedCommands: list[str] = Field(default_factory=list)

    @field_validator("rateLimit")
    @classmethod
    def _check_rate_limit(cls, v: str | None) -> str | None:
        if v is not None and not _RATELIMIT_PATTERN.match(v):
            raise ValueError(f"rateLimit 非法: {v!r}（格式如 10/s、1/m）")
        return v

    @field_validator("timeout")
    @classmethod
    def _check_timeout(cls, v: str) -> str:
        if not _TIMEOUT_PATTERN.match(v):
            raise ValueError(f"timeout 非法: {v!r}（格式如 500ms、10s、1m）")
        return v

    def timeout_seconds(self) -> float:
        m = re.match(r"^(\d+)(ms|s|m)$", self.timeout)
        assert m, f"timeout 无法解析: {self.timeout}"
        n = int(m.group(1))
        unit = m.group(2)
        return n / 1000.0 if unit == "ms" else float(n) if unit == "s" else n * 60.0


class ProtocolBindings(BaseModel):
    """v0.4.0 协议绑定：一个资源在 AGI 协议栈中的三层位置。

    - hardware_side：硬件侧描述协议（MHS 理念落地；非硬件资源为 "none"）
    - agent_access：Agent 访问通道（当前为 MCP）
    - inter_agent：Agent 间协同通道（A2A 为 Hub 级最小端点，资源级可选声明）
    """

    hardware_side: HardwareSide = "none"
    agent_access: list[AgentAccess] = Field(default_factory=lambda: ["mcp"])
    inter_agent: list[InterAgent] = Field(default_factory=list)


class UniSpec(BaseModel):
    """UniSpec v0.4.0 顶层结构（docs/unispec.md §2/§9）。"""

    id: str
    type: ResourceType
    name: str
    description: str | None = None
    protocol: ProtocolType
    endpoint: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[Capability] = Field(min_length=1)
    constraints: Constraints = Field(default_factory=Constraints)
    # ---- v0.4.0 增量（可选字段，缺省时按下文规则自动派生）----
    version: str = "0.4.0"
    protocol_bindings: ProtocolBindings | None = None
    control_mechanisms: list[ControlMechanism] = Field(default_factory=list)
    self_description: dict[str, Any] | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_PATTERN.match(v):
            raise ValueError(f"id 非法: {v!r}（需匹配 {_ID_PATTERN.pattern}）")
        return v

    @field_validator("version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            raise ValueError(f"version 非法: {v!r}（需为 x.y.z 形式）")
        return v

    @model_validator(mode="after")
    def _derive_v04_fields(self) -> "UniSpec":
        """v0.4.0 缺省派生：协议绑定按资源类型补齐，控制机制按消费方式补齐。

        向后兼容：v0.3.x 描述未声明这些字段时，模型自动给出可解释的默认值，
        不要求适配器逐份改写 YAML/JSON。
        """
        if self.protocol_bindings is None:
            self.protocol_bindings = ProtocolBindings(
                hardware_side=("MHS-compatible" if self.type == "iot_device" else "none"),
            )
        if not self.control_mechanisms:
            if self.type == "cli_tool":
                self.control_mechanisms = ["mcp_tool", "cli"]
            elif self.type == "local_script":
                self.control_mechanisms = ["mcp_tool", "code_file"]
            else:
                self.control_mechanisms = ["mcp_tool"]
        return self

    @model_validator(mode="after")
    def _check_multiplicity(self) -> "UniSpec":
        names = [c.name for c in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError(f"capabilities.name 必须唯一: {names}")
        return self

    @model_validator(mode="after")
    def _check_type_protocol(self) -> "UniSpec":
        expected: dict[str, str] = {
            "iot_device": "mqtt",
            "cli_tool": "subprocess",
            "rest_api": "http",
            "local_script": "script",
            "database": "sqlite",
            "websocket_stream": "websocket",
        }
        want = expected[self.type]
        if self.protocol != want:
            raise ValueError(f"type={self.type} 要求 protocol={want}，实际为 {self.protocol}")
        if self.type in ("cli_tool", "local_script") and not any(
            c.command for c in self.capabilities
        ):
            raise ValueError(f"type={self.type} 的 capability 必须声明 command 模板")
        return self

    def mcp_tools(self) -> list[dict[str, Any]]:
        """生成 MCP Tool 定义列表（tools/list 返回结构）。"""
        bindings = (self.protocol_bindings.model_dump()
                    if self.protocol_bindings is not None else {})
        tools = []
        for c in self.capabilities:
            tools.append(
                {
                    "name": c.name,
                    "title": c.title or c.name,
                    "description": c.description,
                    "inputSchema": c.inputSchema,
                    "annotations": {
                        "readOnlyHint": c.readOnly or self.constraints.readOnly,
                    },
                    # v0.4.0：工具定义携带协议绑定与控制机制（Agent 可自描述发现）
                    "_meta": {
                        "unispec": {
                            "version": self.version,
                            "resource_type": self.type,
                            "protocol_bindings": bindings,
                            "control_mechanisms": list(self.control_mechanisms),
                        },
                    },
                }
            )
        return tools
