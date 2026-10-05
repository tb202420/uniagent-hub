# UniSpec v0.3.0 — 统一能力描述规范

> 状态：**已冻结** · 版本：v0.3.0 · 日期：2026-09-26（v0.1 冻结于 2026-09-25，v0.2 冻结于 2026-09-26）
> 变更需走评审流程，禁止直接修改后发布。版本差异见文末「§11 变更记录」。
> v0.3.0 评审通过依据：2026-09-26 全面复盘规划（A3 跨平台 CLI 模板 / B9 数据库适配器 / A4 设备状态 retain），经用户人工审核批准。

## 1. 设计目标

- **单一模型描述所有资源**：IoT 设备、CLI 工具、REST API、本地脚本、数据库；
- **机器可读**：JSON Schema 校验，注册中心直接入库；
- **可生成 MCP Tool**：每条 `capability` 可 1:1 映射为 MCP `Tool`（name/title/description/inputSchema）；
- **安全声明**：`constraints` 中声明只读、限流、权限、沙箱路径。

## 2. 顶层结构

```json
{
  "id": "string, 全局唯一，形如 cli.git.status",
  "type": "iot_device | cli_tool | rest_api | local_script | database",
  "name": "string, 展示名",
  "description": "string, 可选",
  "protocol": "mqtt | http | subprocess | script | stdio | sqlite",
  "endpoint": { "...": "按 type 定制，见 §3" },
  "capabilities": [ "见 §4" ],
  "constraints": { "见 §5" }
}
```

## 3. 各类型的 endpoint 约定

| type | protocol | endpoint 结构 |
|---|---|---|
| `iot_device` | `mqtt` | `{ "broker": "mqtt://host:1883", "topic": "home/livingroom/temp" }` |
| `cli_tool` | `subprocess` | 无（命令在 `capabilities` 模板中声明） |
| `rest_api` | `http` | `{ "base_url": "https://api.example.com", "auth": "apikey_header" }` |
| `local_script` | `script` | `{ "path": "/opt/scripts/backup.py", "interpreter": "python3" }` |
| `database` | `sqlite` | `{ "path": "data/uniagent_demo.db", "engine": "sqlite" }`（v0.3.0，B9） |

## 4. capability（能力项）

每条 `capability` 是平台暴露给 Agent 的一个 MCP Tool：

```json
{
  "name": "get_temperature",            // camelCase，MCP Tool 名
  "title": "获取温度",                  // 可选，展示名
  "description": "获取客厅当前温度",
  "inputSchema": {                       // JSON Schema draft-07，MCP inputSchema
    "type": "object",
    "properties": { "room": { "type": "string", "enum": ["bedroom", "livingroom"] } },
    "required": ["room"]
  },
  "outputSchema": { "type": "number", "unit": "celsius" },
  "readOnly": true,                      // 声明只读，Guard 强校验
  "rateLimit": "1/s",                    // 可选，覆盖全局限流
  "stateField": "temperature",           // v0.2 IoT：从状态 payload 取该字段作为输出
  "paramPatterns": { "room": "^[a-z]+$" }, // v0.2 注入防护：参数名 → 白名单正则
  "permissionLevel": null                // v0.2 权限：能力级覆盖，见下方优先级
}
```

**权限判定优先级（v0.2.0，Guard 实现）**：

```
required = cap.permissionLevel ?? (cap.readOnly ? "read" : spec.constraints.permissionLevel)
```

- `readOnly` 能力自动降为 `read`（最小权限原则，即使资源级要求 write）；
- `cap.permissionLevel` 显式声明时优先于一切推断 —— 支持设备级加固
  （如门锁的"状态查询"虽然只读，但管理员要求 write 级授权才可调用）；
- 向后兼容：v0.1 规范的能力项无此字段，行为不变。

**`stateField` 缺省时的字段推断（v0.2.0，MQTT 适配器）**：工具名形如 `get_X`
且状态 payload 中恰有键 `X` 时取 `state.X`，否则返回完整状态对象
（支持 `get_ac_state` 这类整体状态查询）。

## 5. constraints（约束声明）

```json
{
  "readOnly": false,                     // 整个资源是否只读
  "permissionLevel": "read | write | admin",   // 调用所需最低权限
  "rateLimit": "10/m",                   // 全局限流（单位 s/m/h/d，禁止写 10/min）
  "timeout": "10s",                      // 单次调用超时（ms/s/m）
  "allowedPaths": ["/tmp/workspace"],    // CLI/脚本沙箱文件系统白名单
  "allowedCommands": ["git", "find"]     // CLI 白名单（禁止 raw shell）
}
```

> **限流格式注意**：单位只允许 `s / m / h / d` 单字符（如 `10/m`）。
> `10/min` 这类写法会被模型校验拒绝（阶段 2 实测踩坑）。

## 6. 完整示例

### 6.1 IoT 设备（MQTT）

```json
{
  "id": "iot.livingroom.temp_sensor",
  "type": "iot_device",
  "name": "客厅温度传感器",
  "protocol": "mqtt",
  "endpoint": { "broker": "mqtt://localhost:1883", "topic": "uniagent/devices/temp_01/state" },
  "capabilities": [
    {
      "name": "get_temperature",
      "description": "获取客厅当前温度（摄氏度）",
      "inputSchema": { "type": "object", "properties": {} },
      "outputSchema": { "type": "number", "unit": "celsius" },
      "readOnly": true
    }
  ],
  "constraints": { "readOnly": true, "permissionLevel": "read", "rateLimit": "1/s", "timeout": "3s" }
}
```

### 6.2 CLI 工具

```json
{
  "id": "cli.git.status",
  "type": "cli_tool",
  "name": "Git 状态查询",
  "protocol": "subprocess",
  "capabilities": [
    {
      "name": "git_status",
      "description": "查看指定仓库的 Git 状态",
      "command": "git status --short",                    // 模板内占位符见 §7
      "inputSchema": {
        "type": "object",
        "properties": { "repo_path": { "type": "string", "pattern": "^[a-zA-Z0-9_/.\\\\-]+$" } },
        "required": ["repo_path"]
      },
      "outputSchema": { "type": "string" },
      "readOnly": true
    }
  ],
  "constraints": { "readOnly": true, "permissionLevel": "read", "timeout": "10s", "allowedPaths": ["/workspace"] }
}
```

### 6.3 REST API（OpenAPI 导入后生成）

```json
{
  "id": "rest.weather.current",
  "type": "rest_api",
  "name": "城市天气查询",
  "protocol": "http",
  "endpoint": { "base_url": "https://api.openweathermap.org/data/2.5", "auth": "apikey_header" },
  "capabilities": [
    {
      "name": "get_weather",
      "description": "获取指定城市当前天气",
      "http": { "method": "GET", "path": "/weather", "queryParams": ["q", "units"] },
      "inputSchema": {
        "type": "object",
        "properties": {
          "q": { "type": "string", "description": "城市名" },
          "units": { "type": "string", "enum": ["metric", "imperial"], "default": "metric" }
        },
        "required": ["q"]
      },
      "outputSchema": { "type": "object" },
      "readOnly": true
    }
  ],
  "constraints": { "readOnly": true, "permissionLevel": "read", "rateLimit": "10/m", "timeout": "5s" }
}
```

### 6.4 本地脚本

```json
{
  "id": "script.report.gen",
  "type": "local_script",
  "name": "生成演示报告",
  "protocol": "script",
  "endpoint": { "path": "/opt/uniagent/scripts/gen_report.py", "interpreter": "python3" },
  "capabilities": [
    {
      "name": "gen_report",
      "description": "生成当日演示报告 Markdown",
      "inputSchema": {
        "type": "object",
        "properties": { "output_dir": { "type": "string", "pattern": "^[a-zA-Z0-9_/.\\\\-]+$" } },
        "required": ["output_dir"]
      },
      "outputSchema": { "type": "string" },
      "readOnly": false
    }
  ],
  "constraints": { "permissionLevel": "write", "timeout": "30s", "allowedPaths": ["/opt/uniagent/reports"] }
}
```

### 6.5 数据库（SQLite，v0.3.0 B9）

```json
{
  "id": "db.demo.query",
  "type": "database",
  "name": "演示数据库·只读查询",
  "description": "只读查询演示数据库（仅 SELECT 单语句）",
  "protocol": "sqlite",
  "endpoint": { "path": "data/uniagent_demo.db", "engine": "sqlite" },
  "capabilities": [
    {
      "name": "db_query",
      "description": "只读查询（SQL 单语句，动词白名单 SELECT，禁止注释/分号）",
      "inputSchema": {
        "type": "object",
        "properties": { "sql": { "type": "string", "pattern": "^[a-zA-Z0-9_().,*'=<>!+\\- /%]+$" } },
        "required": ["sql"]
      },
      "readOnly": true,
      "rateLimit": "20/m"
    }
  ],
  "constraints": { "readOnly": true, "permissionLevel": "read", "timeout": "5s" }
}
```

> 安全说明：数据库适配器使用独立演示库（与 Hub 自身 `uniagent.db` 隔离）；
> 写能力（db_execute）为 `write` 权限 + 动词白名单（INSERT/UPDATE/DELETE）+ 单语句 + 禁止注释。

## 7. CLI 命令模板占位符语法（阶段 2 细化）

- `{arg}` — 必填参数，由 `inputSchema.required` 声明；
- `{arg # 描述}` — 带描述的必填参数，用于自动生成 Schema 的 `description`；
- `[optional]` — 可选参数（不放入 `required`）；
- **跨平台模板（v0.3.0，A3）**：条目可用 `platforms: { linux: {...}, windows: {...} }` 声明
  多套命令模板（操作系统键名：`linux` / `windows` / `darwin`，对应 `sys.platform`），
  模板条目内的 `command / param_patterns / allowed_commands / description` 覆盖顶层同名键；
  宿主平台无对应模板时回退顶层 `command`（平台无关工具，如 `git_status`）。
  示例见 `adapters/cli_adapter/configs/cli_tools.yaml`（file_search：Linux=find / Windows=where /r）；
- **禁止使用** `shell=True` 与字符串拼接执行；参数必须经白名单/正则校验后以 argv 数组传入。

## 8. 设备自动发现协议

设备（或模拟器）上线时向 MQTT 主题发布 UniSpec。**所有 topic 统一携带项目前缀**
（v0.2.0，SUP-03）：使用公共 broker（broker.emqx.io）时，无前缀的 `uniagent/...`
会与他人流量冲突，因此约定前缀默认 `uniagent-hub-rxyc`，可通过环境变量
`HUB_TOPIC_PREFIX` 覆盖（中心化定义见 `adapters/mqtt_adapter/topics.py`）：

```
topic:   {prefix}/register/{device_id}          设备上线注册（UniSpec，retain=True）
         {prefix}/devices/{device_id}/state     状态上报 / 写操作回执（retain=True，v0.3.0 A4：
                                                命令后的状态更新同样保留，Hub 重启/晚订阅即可拿到最新状态）
         {prefix}/devices/{device_id}/command   设备命令（写操作）
payload: <UniSpec JSON>（仅注册 topic）
```

Hub 订阅 `{prefix}/register/+` 与 `{prefix}/devices/+/state`，收到注册后
校验 → 入库 → 生成 MCP Tool；写操作发布到 command topic 并等待 state 回执确认。

## 9. 正式 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://uniagent.hub/spec/unispec-v0.3",
  "title": "UniSpec v0.3.0",
  "type": "object",
  "required": ["id", "type", "name", "protocol", "capabilities"],
  "properties": {
    "id": { "type": "string", "pattern": "^[a-z][a-z0-9_.-]*$" },
    "type": { "enum": ["iot_device", "cli_tool", "rest_api", "local_script", "database"] },
    "name": { "type": "string" },
    "description": { "type": "string" },
    "protocol": { "enum": ["mqtt", "http", "subprocess", "script", "stdio", "sqlite"] },
    "endpoint": { "type": "object" },
    "capabilities": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["name", "description", "inputSchema"],
        "properties": {
          "name": { "type": "string", "pattern": "^[a-z][a-zA-Z0-9_]*$" },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "command": { "type": "string" },
          "http": { "type": "object" },
          "inputSchema": { "type": "object" },
          "outputSchema": { "type": "object" },
          "readOnly": { "type": "boolean", "default": false },
          "rateLimit": { "type": "string", "pattern": "^[0-9]+/[smhd]$" },
          "stateField": { "type": "string" },
          "paramPatterns": { "type": "object", "additionalProperties": { "type": "string" } },
          "permissionLevel": { "enum": ["read", "write", "admin"] }
        }
      }
    },
    "constraints": {
      "type": "object",
      "properties": {
        "readOnly": { "type": "boolean", "default": false },
        "permissionLevel": { "enum": ["read", "write", "admin"], "default": "read" },
        "rateLimit": { "type": "string", "pattern": "^[0-9]+/[smhd]$" },
        "timeout": { "type": "string", "pattern": "^[0-9]+[sm]$" },
        "allowedPaths": { "type": "array", "items": { "type": "string" } },
        "allowedCommands": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

## 10. 冻结条款

- 字段增删改必须更新本文件版本号并写 CHANGELOG；
- 阶段 1 内不允许改名 `capabilities`、`inputSchema` 等顶层/核心字段；
- 新增资源类型（如 `database`）时，先扩展 enum 并补充示例。

## 11. 变更记录

### v0.3.0（2026-09-26，全面复盘修复批次，经人工评审批准）

| 处 | 变更 | 原因 |
|---|---|---|
| §2/§3/§9 | `type` 枚举新增 `database`，`protocol` 枚举新增 `sqlite`（§6.5 示例） | B9：新增第五类适配器（数据库），"一规范多类型"覆盖数据库资源 |
| §7 | CLI 模板新增 `platforms` 跨平台声明（`linux`/`windows`/`darwin`，模板键覆盖顶层同名键） | A3：file_search 在 Windows 上使用 `where /r`、Linux 上使用 `find` |
| §8 | 设备状态 topic 明确 `retain=True`（含命令后的状态更新） | A4：Hub 重启后 `get_ac_state` 读到陈旧 retained 初始状态 |

### v0.2.0（2026-09-26，最终检查修复批次）

| 处 | 变更 | 原因 |
|---|---|---|
| §4 | capability 新增 `stateField`（IoT 状态映射）、`paramPatterns`（参数白名单）、`permissionLevel`（能力级权限覆盖）及权限优先级公式 | 阶段 1-3 实现已使用这三个字段但规范未收录（契约漂移）；权限公式支持设备级加固场景 |
| §5/§6.3 | 限流单位明确为 `s/m/h/d` 单字符；修正示例 `10/min` → `10/m` | 原示例自身违反了 Schema 的 `^[0-9]+/[smhd]$` 约束（ERR-06，复刻了阶段 2 的真实踩坑） |
| §8 | 设备发现协议 topic 统一加项目前缀 `uniagent-hub-rxyc`（`HUB_TOPIC_PREFIX` 可覆盖） | 公共 broker 上无前缀 topic 会与他人流量冲突（SUP-03 演示隔离） |
| §9 | JSON Schema 同步收录上述 capability 新字段 | 与实现一致 |

**兼容性**：三个新字段均可选、缺省行为与 v0.1 完全一致，v0.1 规范描述的资源无需修改即可注册。

### v0.1（2026-09-25，阶段 0 冻结）

初次冻结：顶层结构、四类 endpoint 约定、capability、constraints、CLI 模板占位符、设备发现协议、JSON Schema。
