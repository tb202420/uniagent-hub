# 阶段 3 设计方案：从单工具调用到多工具编排，从只读监测到闭环控制

> 日期：2026-09-25 · 对应 roadmap 阶段 3 · 状态：已实现并验收

## 一、设计目标

1. **写操作闭环**：MQTT 只读 → 可写（ac_control），命令-回执闭环
2. **多工具编排**：`run_workflow` 一次调用完成多步（测温 → 判阈值 → 开空调）
3. **Guard v2**：限流（按 tool+caller+scope）+ 工作流级防护（递归/调用上限/失败传播）
4. **CLI 反向生成**：MCP Tool → 可执行 CLI 脚本（双向能力）
5. **审计 Web 界面**：FastAPI + 纯 HTML，概览/审计/工作流三页

## 二、MQTT 写操作（ac_control）

- UniSpec：`endpoint.command_topic` 声明命令主题；`action` enum 白名单 + `temperature` 16-30 范围约束（Guard 自动生效）
- 适配器：`_call_write()` —— publish(command_topic, qos=1) → 轮询 state_topic 等回执（3s 超时）→ 回执丢失返回"命令已发送，状态未确认"（不阻塞工作流）
- 模拟器 `sim_ac.py`：订阅命令 → 更新状态 → 发布回执，形成闭环
- 权限：`permissionLevel: write`，read 调用方被 Gateway 1003 拦截

## 三、WorkflowEngine

```
JSON 蓝图 → 校验（id 唯一/依赖存在/递归禁止/环检测 fail-fast）
  → Kahn 拓扑排序 → 依序执行：
      - 失败传播：依赖 error/skipped → 本步骤 skipped
      - 单工具调用上限（max_step_calls_per_tool，防循环失控）
      - 条件分支（自研安全解析器，零 eval）
      - 数据管道 {{sN.output[.字段]}} / {{params.xxx}}，支持算术
      - 每步走 gateway.call()（Guard + 审计不旁路），rate_scope 隔离限流桶
```

- 安全表达式：`core/workflow/expr.py` 递归下降解析（数字/字符串/比较/逻辑/算术），注入字符串抛 ExprError
- 递归防护：蓝图注册期拒绝 `run_workflow` 作为步骤工具
- 暴露：`run_workflow` 作为内置 MCP 工具（write 级），tools/list 可见

## 四、Guard v2

| 能力 | 实现 |
|---|---|
| 工具级限流 | `RateLimiter` 滑动窗口，按 (tool, caller, scope)，1004 拦截，超限入审计 |
| 工作流整体限流 | `run_workflow` 单独 10/m |
| scope 隔离 | 工作流内步骤用 `wf:<trace_id>` 桶，不与外部调用互挤占 |
| 递归检测 | 注册期禁止工作流内调用 run_workflow |
| 失败传播 | 依赖失败 → 下游 skipped（返回部分结果，不静默失败） |

## 五、CLI 反向生成

- `core/cli_gen/generator.py`：按 inputSchema 生成 argparse + httpx 脚本到 `generated_cli/`
- 生成的脚本与 MCP `tools/call` 等价（实测 gen_get_temperature.py 运行成功）
- 输出含 README；禁止 eval/exec/shell 拼接

## 六、审计 Web 界面

- `web/audit_dashboard/`：FastAPI + 纯 HTML（无前端构建、无 CDN 依赖，离线可用）
- 页面：`/` 概览（工具数/调用统计）、`/audit` 分页筛选表格（SQLite 数据源）、`/workflows` 工作流执行链路
- 可选 Basic Auth（HUB_DASH_USER/PASS）
- 数据源：Hub 的 SQLite 审计表 + Hub 的 `/workflows/recent` 接口

## 七、验收结果摘要（详见 docs/test-reports/phase3_test_report.md）

- 119 个测试全绿（含安全表达式注入用例、限流、工作流、契约）
- E2E：一次 run_workflow 完成 3 步闭环（29.9°C → 天气 → 空调 on/27°C，3.97s）
- 限流：ac_control 第 6 次 1004；工作流内步骤不挤占外部额度
- CLI：8 个脚本生成且可运行；Dashboard 三页 200

## 八、关键工程决策记录

| 决策 | 理由 |
|---|---|
| 条件表达式自研解析器（不用 simpleeval/eval） | 零依赖 + 答辩可完整解释安全边界 |
| ac_control 温度用 number 而非 integer | 传感器算术结果为浮点，范围 16-30 仍强约束 |
| 工作流失败返回部分结果 + 明细 | Agent 可读每步状态，符合"返回部分结果"设计 |
| 工作流步骤限流 scope 隔离 | 防止预检调用挤占工作流内配额（防误伤） |
| REST 只读缓存 300s | 公共 API 慢/抖动演示兜底 |
| YAML 裸 on/off 必须加引号 | YAML 1.1 会解析为布尔（PyYAML 陷阱） |
