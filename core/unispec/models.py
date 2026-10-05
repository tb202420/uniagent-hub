"""UniSpec v0.2.0 — 统一能力描述规范（契约见 docs/unispec.md，已冻结）。

Pydantic 模型 + 校验。所有适配器与注册中心共享此模型。
v0.2.0 新增 capability 扩展字段：stateField / paramPatterns / permissionLevel。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---- 枚举约束（与 docs/unispec.md §9 保持一致）----

# v0.3.0（B9 修复批次）新增 "database"/"sqlite"：第五类资源（数据库）
ResourceType = Literal["iot_device", "cli_tool", "rest_api", "local_script", "database"]
ProtocolType = Literal["mqtt", "http", "subprocess", "script", "stdio", "sqlite"]
PermissionLevel = Literal["read", "write", "admin"]

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


class UniSpec(BaseModel):
    """UniSpec v0.1 顶层结构（docs/unispec.md §2/§9）。"""

    id: str
    type: ResourceType
    name: str
    description: str | None = None
    protocol: ProtocolType
    endpoint: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[Capability] = Field(min_length=1)
    constraints: Constraints = Field(default_factory=Constraints)

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_PATTERN.match(v):
            raise ValueError(f"id 非法: {v!r}（需匹配 {_ID_PATTERN.pattern}）")
        return v

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
                }
            )
        return tools
