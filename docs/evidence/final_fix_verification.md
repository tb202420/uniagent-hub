# 最终检查修复批次 — 试运行验证记录

> 日期：2026-09-26 · 环境：Windows / Python 3.14 / 公共 broker broker.emqx.io（topic 前缀 uniagent-hub-rxyc）
> Hub 端口 8020（本机 8000 被无关进程占用）

## 验证结果：连续 2 轮 8/8 全绿

| # | 验证点 | 结果 | 证据 |
|---|---|---|---|
| V1 | tools/list 统一输出 9 工具 | PASS | git_status, file_search, get_weather, file_summary, get_ac_state, ac_control, get_temperature, get_humidity, run_workflow |
| V2 | **get_ac_state read 权限放行（ERR-03 修复核心）** | PASS | 返回完整状态 `{'action': 'on', 'temperature': 29, ...}`（修复前误 1003） |
| V3 | ac_control read 权限 1003 拒绝 | PASS | `[error 1003] 权限不足: 需要 write，当前 read` |
| V4-pre | get_weather 预热（国际链路抖动需重试） | PASS | 缓存就绪后 0ms |
| V4 | run_workflow office_cooling 3 步闭环 | PASS | `steps=[('s1','ok'),('s2','ok'),('s3','ok')]`，31.0°C → 天气 → 空调 on |
| V4b | 空调写回执生效 | PASS | 状态更新为 `{'action': 'on', 'temperature': 29, 'request_id': ...}` |
| V5 | 注入参数 1007 拦截（回归） | PASS | `pattern="x; rm -rf /"` 被拦截 |
| V6 | get_weather REST 调用 | PASS | open-meteo 真实响应 |

## LLM Agent 脚本降级模式（SUP-01）端到端

```
[agent] 工具发现：9 个工具 (git_status, file_search, get_weather, file_summary,
        get_ac_state, ac_control, get_temperature, get_humidity, run_workflow)
[agent] 固定剧本：查温度 → 温度过高则触发降温工作流
    1. ✓ 31.1 (0ms)
    2. 温度 31.1°C > 28°C → 触发 office_cooling：
       ✓ 3 步全部 ok（s1 测温 31.1 → s2 天气 20.6°C → s3 空调 on/28°C）
```

## 全量测试

- **123 项全部通过**（阶段 3 的 119 项 + 本批次新增 4 项权限优先级回归测试）
- 新增测试：get_ac_state read 放行 / ac_control read 拒绝 / ac_control write 放行 /
  cap.permissionLevel 显式覆盖（门锁加固场景）

## 本批次试运行发现并修复的 3 个新问题

| 问题 | 根因 | 修复 |
|---|---|---|
| 权限修复后 get_ac_state 仍 1006 | sim_ac 仅在收到命令后发布状态，Hub 无初始状态缓存 | sim_ac 上线即发布初始状态（retain=True） |
| 模拟器温度漂移到 36°C，工作流算出 34 > 空调上限 30 失败 | 随机游走无界漂移（±0.6/tick 累积） | 改为均值回归波动（围绕 init-temp ±0.5 内震荡，贴近真实房间热惯性） |
| 工作流内 get_weather ConnectTimeout | open-meteo 国际链路首次连接抖动 | 演示脚本 P4 预热项（重试至成功，缓存 300s） |

## 结论

12 项 ERR + 3 项 SUP 修复全部验证通过；ERR-03（能力级权限）、SUP-03（topic 前缀）、
SUP-01（LLM 可插拔 + 脚本降级）、ERR-11（演示稳定性）在真实公共 broker 环境下实证生效。
