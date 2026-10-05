# 贡献指南（CONTRIBUTING）

感谢关注 UniAgent Hub！本文件说明如何搭建开发环境、跑通测试，以及新增工具 / 适配器时的契约约定。

## 环境准备

```bash
# Python 3.12+（开发实测 3.14）
pip install -r requirements-dev.txt   # 含运行时依赖 + pytest 等开发依赖

# 运行测试（当前基线：全部通过、0 跳过；数字口径见 docs/口径速查表.md）
python -m pytest
```

> Windows 注意：`paho-mqtt` 导入会触发 WMI 查询（部分 Win11 机器上可长达 30s）。
> 项目在 MQTT 适配器与模拟器内已内置快速回退桩，无需额外处理。

## 目录导览

```
core/
  unispec/       UniSpec 模型与校验（七要素：id/type/name/protocol/endpoint/capabilities/constraints）
  registry/      工具注册中心（内存 + SQLite 持久化）
  gateway/       MCP 路由网关（自研 JSON-RPC，默认路径；FastMCP 4 为可选前端）
  guard/         Guard 安全管道（存在性→权限→限流→参数校验→执行→审计）
  workflow/      工作流引擎（拓扑排序 + 零 eval 表达式）
  cli_gen/       CLI 反向生成（MCP Tool → CLI 脚本）
adapters/        五类适配器（mqtt / cli / rest / script / database）
agent/           Demo Agent 与 LLM Agent
web/             审计 Dashboard
tests/           unit / integration / 适配器契约
```

## 新增一个 CLI 工具（最常见）

编辑 `adapters/cli_adapter/configs/cli_tools.yaml`（或用 `HUB_CLI_CONFIGS` 挂载新文件）：

```yaml
cli_tools:
  - id: "cli.example.hello"          # 命名空间.资源.工具
    name: "示例工具"
    command: "git -C {repo_path # 仓库绝对路径} status --short"   # 占位符自动生成 JSON Schema
    tool_name: "hello"               # 可选，缺省由 id 推导
    readOnly: true
    timeout: 10s
    allowed_commands: ["git"]        # 命令白名单（校验 argv 首程序）
```

无需写任何 Python：平台解析模板生成 Schema，`subprocess(argv, shell=False)` 沙箱执行。

## 新增一类适配器

1. 实现统一三方法协议（冻结契约，不可增删）：

```python
class MyAdapter:
    def discover(self) -> list[dict]: ...                     # 注册 UniSpec
    def list_tools(self) -> list[dict]: ...
    def call_tool(self, name: str, args: dict, ctx: CallContext) -> ToolResult: ...
```

2. （推荐）实现可选生命周期回调：`on_startup()` / `on_health_check()` / `on_shutdown()`（鸭子类型，未实现自动跳过）。
3. （可选）以独立包发布并在 `pyproject.toml` 声明入口点，Hub 启动时自动发现，核心零改动：

```toml
[project.entry-points."uniagent_hub.adapters"]
myproto = "uniagent_hub_myproto:MyAdapter"
```

4. 在 `tests/adapters/contract_test.py` 的适配器清单中登记（契约测试会强制审计落盘等横切语义）。

## 冻结契约（改前请先开 issue 讨论）

- **错误码**：1001（工具不存在）~ 1007（注入拦截）、1999（内部错误），语义不得变更；
- **Guard 管道不可旁路**：任何新入口（元工具、工作流、新前端）必须复用 `MCPGateway.call` 全链路；
- **CLI 执行**：仅允许 `subprocess(argv, shell=False)` + 参数白名单 + 命令白名单；
- **UniSpec**：七要素结构与 `id` 命名约束见 `docs/unispec.md`。

## 提交规范

- 前缀：`feat / fix / docs / test / refactor / chore`，中文描述一行说清动机；
- 每个逻辑变更独立提交（仓库提交历史同时作为开发过程证据）；
- 数字口径（工具数 / 测试数 / 性能）一律引用 `docs/口径速查表.md`，不要另起数字。

## 测试要求

- 新增适配器 / Guard 行为 / 网关语义必须有对应测试（unit 或 integration）；
- 交互式安全行为（权限、限流、注入拦截）请参考 `tests/integration/test_gateway_auth.py` 的写法；
- CI（`.github/workflows/ci.yml`）在 ubuntu / windows × Python 3.12 / 3.14 上跑同一套 pytest。
