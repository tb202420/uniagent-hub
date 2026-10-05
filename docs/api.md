# UniAgent Hub — 接口契约文档

> 版本：v0.5 · 日期：2026-10-04
> 本文件是阶段 0 的核心交付物：**接口冻结后，各模块按此契约并行开发，不允许随意改动**。
> 版本差异见文末「变更记录」（§7）。

## 1. 传输层约定

| 项 | 约定 |
|---|---|
| 协议 | MCP（JSON-RPC 2.0） |
| 传输 | Streamable HTTP（现役，无状态）；stdio 为未来扩展预留（v0.3，B3） |
| 协议前端（v0.4） | 自研 JSON-RPC 2.0（默认/回退）或 **FastMCP 4**（`--gateway fastmcp`，元工具暴露，执行语义一致；服务端点 `POST /mcp`，冒烟证据 `docs/evidence/fastmcp_http_smoke_20261004.txt`） |
| HTTP 端点 | `POST /mcp`，`Content-Type: application/json` |
| 路径前缀 | 网关暴露 `/mcp` 与 `/healthz` |
| 兼容 | 同时支持 2026-07-28（无状态）与 2025-11-25（有状态 initialize） |

## 2. MCP Gateway 核心接口

### 2.1 `tools/list` — 工具发现

请求：
```json
{ "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {} }
```

响应：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "get_temperature",
        "title": "获取客厅温度",
        "description": "获取客厅当前温度（摄氏度）",
        "inputSchema": { "type": "object", "properties": {} },
        "annotations": { "readOnlyHint": true, "titleHint": "获取客厅温度" }
      }
    ]
  }
}
```

> 所有适配器注册的 capability 统一汇入此列表，Agent 无法区分背后类型 —— 这是核心主张的验收点。
>
> 当前注册计数（2026-10-04 实测）：全量档 **22 个**（软件档 11 + 硬件档 8 + 温室模拟节点 3），
> 日常演示档 **14 个**（软件档 11 + 温室模拟节点 3），档位隔离。

### 2.2 `tools/call` — 工具调用

请求：
```json
{
  "jsonrpc": "2.0", "id": 2, "method": "tools/call",
  "params": {
    "name": "get_temperature",
    "arguments": { "room": "livingroom" },
    "caller": "llm_agent",
    "trace_id": "ab12cd34",
    "permission_level": "read"
  }
}
```

`params` 扩展字段（Guard 上下文，均可省略）：

| 字段 | 默认 | 说明 |
|---|---|---|
| `caller` | `"demo_agent"` | 调用方标识，参与限流维度与审计 |
| `trace_id` | 随机生成 | 全链路追踪 ID |
| `permission_level` | `"read"` | `read / write / admin`；权限不足返回 1003 |
| `rate_scope` | `"external"` | 限流桶隔离（工作流内部步骤用 `wf:<trace>`，不挤占外部配额） |

响应（成功）：
```json
{
  "jsonrpc": "2.0", "id": 2,
  "result": {
    "content": [ { "type": "text", "text": "26.5" } ],
    "isError": false,
    "meta": { "latency_ms": 120 }
  }
}
```

响应（失败/拦截）：
```json
{
  "jsonrpc": "2.0", "id": 2,
  "result": {
    "content": [ { "type": "text", "text": "参数校验失败: room 必须为 ['bedroom','livingroom']" } ],
    "isError": true,
    "meta": { "error_code": 1002, "guard": "input_schema" }
  }
}
```

### 2.3 `server/discover` — 能力预宣告（阶段 2 已实现）

请求：
```json
{ "jsonrpc": "2.0", "id": 3, "method": "server/discover", "params": {} }
```

响应（与实现一致，含工作流能力宣告）：
```json
{
  "jsonrpc": "2.0", "id": 3,
  "result": {
    "protocolVersion": "2026-07-28",
    "supportedVersions": ["2026-07-28", "2025-11-25"],
    "capabilities": {
      "tools": { "listChanged": true },
      "workflows": { "supported": true }
    },
    "serverInfo": { "name": "uniagent-hub", "version": "0.3.0" }
  }
}
```

> `workflows.supported` 仅在加载了 WorkflowEngine 时出现；Agent 据此判断是否可用 `run_workflow`。

### 2.4 `run_workflow` — 工作流编排（阶段 3 已实现）

**设计原则：只执行服务端预定义蓝图（`core/workflow/workflows.yaml`），Agent 不传动态 steps。**

理由（答辩要点）：动态 steps 意味着把编排逻辑开放给调用方，恶意/错误蓝图可造成资源滥用与递归调用；预定义蓝图在注册期完成校验（拓扑成环、递归调用、步骤数上限），运行期仅接受参数注入，安全面收敛到最小。

请求：
```json
{
  "jsonrpc": "2.0", "id": 4, "method": "tools/call",
  "params": {
    "name": "run_workflow",
    "arguments": { "workflow": "office_cooling", "params": {} },
    "caller": "llm_agent",
    "permission_level": "write"
  }
}
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `workflow` | 是 | 蓝图名，enum 来自 `workflows.yaml`（tools/list 中可见） |
| `params` | 否 | 蓝图入参，占位符 `{{params.x}}` 注入 |

约束：
- `run_workflow` 为 **write 级**（可触发写操作），read 权限返回 1003；
- 工作流整体限流 10/m（错误码 1004）；
- 每步仍逐个走 Guard 管道（校验/权限/限流/审计），不旁路安全；
- 部分步骤失败：失败步骤起下游标记 `skipped`，整体返回错误明细 JSON + 1999。

### 2.5 鉴权（Bearer Token，安全批次 2026-10-04）

- 网关默认监听 `127.0.0.1`，不对外暴露（演示环境默认安全边界）；
- 设置环境变量 `HUB_API_TOKEN` 后，`/mcp` 与 `/workflows/recent` 需携带
  `Authorization: Bearer <token>`；缺失/错误返回 **HTTP 401**（未授权），JSON-RPC 层对应错误码 **-32001**；
- 鉴权开启时**权限由服务端裁决**：认证通过=admin、未认证=read；客户端 `permission_level` 仅作提示，
  不再作为授权依据（防客户端自报越权）；
- **FastMCP 前端同受 Bearer 覆盖（P2）**：`--gateway fastmcp` 不经过自研 `create_app`，设置
  `HUB_API_TOKEN` 后由 FastMCP ASGI 入口的前端中间件做同样校验（HTTP 401 / -32001）；前端经受信
  中继执行（`internal=True`），身份取自 `HUB_FASTMCP_CALLER` / `HUB_FASTMCP_PERMISSION`，
  鉴权模式下写操作按配置裁决、不降权也不旁路（`execute_tool` 中继语义一致）；
- SSRF 增强：域名先 DNS 解析校验 + 非常用端口拒绝（`HUB_REST_CHECK_DNS=0` 可关闭 DNS 校验）。

## 3. 适配器统一接口（Python 契约）

所有适配器实现同一协议，由 Gateway 统一调度。**阶段 1 即按此实现 CLI 适配器**。

```python
from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass(frozen=True)
class CallContext:
    """一次 tools/call 的上下文，贯穿 Guard → 适配器 → 审计。"""
    trace_id: str
    caller: str                    # Agent / 调用方标识
    permission_level: str = "read" # read | write | admin


@dataclass
class ToolResult:
    ok: bool
    data: Any
    error_code: int = 0
    error_msg: str = ""
    latency_ms: int = 0


class BaseAdapter(Protocol):
    """适配器统一协议。新增资源类型 = 新增实现，核心层零改动。"""

    def discover(self) -> list[dict]:
        """返回该适配器管理的全部 UniSpec 描述（含自动发现的设备）。"""

    def list_tools(self) -> list[dict]:
        """返回 MCP Tool 定义列表（name/title/description/inputSchema）。"""

    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult:
        """执行工具调用。必须：先校验参数、记录 trace_id、返回结构化结果。"""
```

## 4. 错误码约定

| code | 含义 | 触发点 |
|---|---|---|
| 0 | 成功 | — |
| 1001 | 工具不存在 | Gateway 路由 |
| 1002 | 参数校验失败 | Guard |
| 1003 | 权限不足 | Guard |
| 1004 | 超出速率限制 | Guard |
| 1005 | 调用超时 | 适配器沙箱 |
| 1006 | 资源不可用（设备离线 / API 不可达） | 适配器 |
| 1007 | 命令注入风险拦截 | Guard |
| 1999 | 内部错误 | 任意 |

## 5. 审计日志字段（Guard 强制写入）

```json
{
  "trace_id": "ab12cd34",
  "ts": "2026-10-03T10:00:00Z",
  "caller": "demo_agent",
  "tool": "ac_control",
  "args": { "action": "on" },
  "guard_result": "passed | blocked",
  "block_reason": "",
  "result": { "ok": true },
  "error_code": 0,
  "schema_hash": "3f2a…（工具定义内容哈希）",
  "latency_ms": 150,
  "pre_hash": "（仅 HUB_AUDIT_CHAIN=1 时写入）",
  "rec_hash": "（同上：审计哈希链，防篡改）"
}
```

> `error_code`（v0.3，A2）：拦截/失败时的数字错误码（1001–1007 / 1999，见 §4）；
> `passed` 时为 0。Dashboard 审计页可按错误码直接筛选（如 `1007`）。
> `schema_hash`（v0.4）：被调工具定义（name/description/inputSchema）的 SHA-256 内容哈希，
> 用于工具投毒防护的事后追溯（见 `core/guard/attestation.py`）。
> `pre_hash` / `rec_hash`（v0.4）：可选的审计哈希链字段（`HUB_AUDIT_CHAIN=1` 时逐条链接，
> `scripts/attestation.py audit-verify` 可校验完整性）。

## 6. 冻结条款

1. 阶段 1 内 `tools/list` / `tools/call` 响应结构不得变更；
2. 适配器三方法签名（`discover/list_tools/call_tool`）不得变更；
3. 错误码 1001–1007 语义不得变更；
4. 变更必须更新本文件版本号并说明兼容性。

## 7. 变更记录

### v0.5.1（2026-10-05，P2 加固批次）

| 处 | 变更 | 原因 |
|---|---|---|
| §2.5 | FastMCP 前端（`--gateway fastmcp`）同受 Bearer 覆盖：`HUB_API_TOKEN` 设置后 ASGI 入口同样 401 / -32001；前端经 `internal=True` 受信中继，身份取自 `HUB_FASTMCP_CALLER` / `HUB_FASTMCP_PERMISSION` | 此前 FastMCP 前端绕过自研 Bearer 中间件（P2 遗留项） |
| §5 | 审计 SQLite 表主键改为自增 `id`，`trace_id` 降级为索引关联键；老库自动迁移（记录全量保留）；`INSERT OR REPLACE` → 普通 `INSERT` | trace_id 客户端可控，主键冲突会静默覆盖历史审计记录 |

### v0.5（2026-10-04，安全批次）

| 处 | 变更 | 原因 |
|---|---|---|
| §2.5 | 新增 Bearer Token 鉴权：设 `HUB_API_TOKEN` 后 `/mcp` 与 `/workflows/recent` 需 `Authorization: Bearer`；HTTP 401=未授权，JSON-RPC 错误码 -32001；网关默认监听 127.0.0.1 | 网关鉴权（安全批次） |
| §2.5 | 鉴权开启时权限由服务端裁决（认证=admin、未认证=read；客户端 `permission_level` 仅作提示） | 防客户端自报越权 |
| §2.5 | SSRF 增强（域名 DNS 解析校验 + 非常用端口拒绝）+ 审计面板全部输出 HTML 转义 | SSRF 纵深防御 / 防 XSS |
| §2.1 | 工具计数更新：全量 22（软件档 11 + 硬件档 8 + 温室模拟 3）/ 演示档 14 | 口径核定 |

### v0.4（2026-10-03，改进方案第 1 批）

| 处 | 变更 | 原因 |
|---|---|---|
| §2.3 | 新增 `server/attestation` 方法：返回全部工具的内容哈希（+可选 Ed25519 签名） | 改进规划 §5.1 工具投毒防护工程化落地 |
| §2.1 | `tools/list` 支持**渐进式发现模式**（`HUB_META_TOOLS=1` 时仅返回 4 个元工具：`discover_tools` / `get_tool_schema` / `execute_tool` / `refresh_registry`；`execute_tool` 透传完整 Guard 管道，语义与 `tools/call` 一致） | 改进规划 §3（100+ 工具场景上下文可控） |
| §5 | 审计记录新增 `schema_hash`（默认开启）与 `pre_hash` / `rec_hash`（哈希链，可选） | §5.1 追溯 + §5.3 防篡改 |
| §1/§2.1 | `/healthz` 新增 `adapters` 字段（各适配器健康状态）；协议前端可选 FastMCP 4 | 改进规划 §2/§4 |
| §3 | 适配器协议扩展**可选生命周期回调**（`on_startup` / `on_health_check` / `on_shutdown`）与 entry_points 插件自动发现；三方法签名不变（向后兼容） | 改进规划 §4 插件式架构 |
| §3/§4 | REST 适配器：`requestBody` → **JSON body 实际发送**（`body_*` 参数）；设备类 Spec（含写能力）禁用只读缓存 | 硬件测试 2（智能插座 POST）必需；修复写后读不一致 |

### v0.3（2026-09-26，全面复盘修复批次，经人工评审批准）

| 处 | 变更 | 原因 |
|---|---|---|
| §2.1 | `run_workflow` 通过 `registry.register_tool` 注册进注册中心，`tools/list` 与 `/healthz` 计数统一由注册中心提供（9→11 个工具计数一致） | A1：healthz 报 8 而 tools/list 返回 9，计数口径不一致 |
| §5 | 审计记录新增 `error_code` 字段（数字错误码落 SQLite/JSONL，Dashboard 可按错误码筛选） | A2：此前 SQLite `audit.error_code` 列恒为 0，无法按 1007/1003/1004 检索 |
| §3 | 适配器协议新增现役第五类适配器（数据库，B9）：`db_query`/`db_execute`，`type=database`/`protocol=sqlite` | B9：五类适配器覆盖 |
| §1 | 传输说明：现役传输为 Streamable HTTP；stdio 为未来扩展预留 | B3：文档与实现对齐 |

### v0.2（2026-09-26，最终检查修复批次）

| 处 | 变更 | 原因 |
|---|---|---|
| §2.2 | 补充 `tools/call` 的 `caller / trace_id / permission_level / rate_scope` 扩展字段说明 | 阶段 1-3 实现已支持但文档未收录（ERR-05 契约漂移） |
| §2.3 | `server/discover` 响应结构对齐实现：`protocolVersions` → `protocolVersion` + `supportedVersions`；补 `workflows` 能力宣告 | 实现与文档不一致（ERR-04） |
| §2.4 | `run_workflow` 契约重写：**Agent 只传 `workflow` + `params`，不传动态 `steps`**；补充权限/限流/失败传播约束 | 阶段 3 设计决策：预定义蓝图安全性优于动态编排，文档需如实记录设计理由 |

### v0.1（2026-09-25，阶段 0 冻结）

初次冻结：传输层、tools/list、tools/call、server/discover（契约先行）、适配器协议、错误码、审计字段。
