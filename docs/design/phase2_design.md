# 阶段 2 设计方案：一规范多类型（SQLite 持久化 + REST/脚本适配器）

> 日期：2026-09-25 · 对应 roadmap 阶段 2 · 状态：已实现并验收

## 一、设计目标

在阶段 1（CLI + MQTT）基础上，完成"一规范多类型"核心主张：
同一套 `tools/list` / `tools/call` 管道下，IoT、CLI、REST、本地脚本四类资源无差别调用；
工具与审计持久化到 SQLite，重启后工具仍在。

## 二、架构变更

```
阶段 1: Registry(内存) ── Gateway ── 适配器(CLI/MQTT)
阶段 2: Registry(SQLite 落盘) ── Gateway ── 适配器(CLI/MQTT/REST/Script)
                                        └── SQLiteStore(tools + audit 表, WAL)
```

- `core/registry/store.py`：SQLiteStore —— tools / audit 两表，WAL 模式，线程安全（单连接 + 锁）
- `core/registry/registry.py`：register/unregister 同步落库；`load_from_store()` 启动恢复
- `core/guard/audit.py`：JSONL + SQLite 双写过渡，查询优先走 SQLite（tool + 时间范围）

## 三、REST 适配器设计

### 3.1 流程
```
OpenAPI Spec(本地文件/URL, YAML/JSON)
  → load_spec + 内部 $ref 解析(循环检测/深度限制/外部引用降级)
  → 遍历 paths×methods → operationId → MCP Tool
  → path/query/header 参数 + requestBody(body_ 前缀) → inputSchema
  → GET/HEAD/OPTIONS → readOnly=true
  → 注册 ToolRegistry
```

### 3.2 安全设计（答辩重点）
| 措施 | 实现 |
|---|---|
| SSRF 防护 | 仅允许 Spec 声明的 servers（或显式覆写）；拒绝 127.*/10.*/192.168.*/169.254.* 等私有保留地址；不跟随重定向 |
| 认证脱敏 | API Key 从环境变量读取注入 Header，不进参数、不进审计 |
| 超时与上限 | httpx timeout=10s；响应 >1MB 截断并标注 |
| 参数校验 | 复用 Gateway Guard 横切管道（inputSchema + 注入白名单） |

### 3.3 演示工具
`get_weather`（open-meteo）：免费、无需 Key、有 OpenAPI；演示"查询天气 → 工作流联动"。

## 四、脚本适配器设计

- **不做进程内 exec**（答辩：评委必问"Agent 能否执行任意代码"），复用 CLI subprocess 沙箱
- argv 数组执行（shell=False）+ 参数走 Guard 横切
- **路径白名单**：entry 必须位于 `scripts/` 目录下，`../` 逃逸在注册与执行两层拒绝
- 脚本 stdout 输出 JSON，适配器解析后结构化返回；工作目录固定为 scripts root

## 五、契约测试（质量闸门）

`tests/adapters/contract_test.py`：对所有适配器跑同一组用例——
统一 list_tools 结构、未知参数 1002/注入 1007、越权 1003、审计必写。
新增适配器必须通过方可合入。

## 六、验收结果摘要（详见 docs/test-reports/）

- 79 个测试全绿
- E2E：6 工具统一注册；get_weather 真实调用成功；file_summary 115ms
- SQLite：5 资源落库（含自动发现的 IoT 设备），审计可查询
- 重启恢复：Hub 重启后 tools/list 仍为 6 工具
- Guard 横切：4 类适配器统一拦截未知参数/注入；越权 1003
