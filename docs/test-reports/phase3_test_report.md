# 阶段 3 测试报告

> 日期：2026-09-25 · 范围：MQTT 写操作 / WorkflowEngine / Guard v2 / CLI 反向生成 / Web 界面

## 一、测试结果汇总

| 项 | 结果 | 说明 |
|---|---|---|
| 全量测试 | **119 passed** | 含安全表达式（注入用例）、限流、工作流、契约、CLI 生成、MQTT 写操作 |
| 工作流 E2E | ✅ | 一次 `run_workflow` 3 步闭环（get_temperature 29.9 → get_weather → ac_control on/27°C），3.97s |
| 写操作闭环 | ✅ | 空调状态回执确认（sim_ac 命令→状态） |
| 条件分支 | ✅ | 29.9 > 28 触发 s3；<28 场景单测验证 skipped |
| 数据管道 | ✅ | `{{s1.output}} - 2` → 29.9-2=27.9 → 27（整值规整） |
| 限流 | ✅ | ac_control 第 6 次 1004（5/m）；工作流内步骤 scope 隔离不误伤 |
| 递归防护 | ✅ | 注册期拒绝工作流内调用 run_workflow（单测） |
| 失败传播 | ✅ | 依赖失败 → 下游 skipped（单测） |
| CLI 反向生成 | ✅ | 8 个脚本；gen_get_temperature.py 实跑成功（28.6） |
| Web 界面 | ✅ | `/` `/audit` `/workflows` 三页 HTTP 200 |

## 二、安全测试

| 用例 | 结果 |
|---|---|
| 表达式注入：`__import__('os')` / `open(...)` / `globals()` / `lambda` 等 | ExprError 拒绝 ✅ |
| 除零 / 字符串比较 / 多余 token | ExprError ✅ |
| ac_control action enum（on/off 白名单） | 越界值 1002 ✅ |
| ac_control temperature 范围 16-30 | 越界 1002（单测）✅ |
| read 权限调用 ac_control / run_workflow | 1003 ✅ |
| 工作流递归（步骤含 run_workflow） | 注册期拒绝 ✅ |
| 限流（外部 5/m 桶） | 第 6 次 1004 ✅ |

## 三、性能观测

| 调用 | 延迟 |
|---|---|
| run_workflow（3 步，含 open-meteo 冷调用） | 3969ms 总耗时 |
| get_temperature（MQTT 缓存） | 0ms |
| get_weather（首次冷调用） | 2850ms（缓存后 0ms） |
| ac_control（含回执等待） | 1104ms |
| gen_get_temperature.py（CLI 等价） | ~200ms |

## 四、复现命令

```bash
# 全量测试
python -m pytest tests/ -q

# 启动（另起终端分别运行）
python main.py --port 18423
python -m adapters.mqtt_adapter.simulator --broker mqtt://broker.emqx.io:1883 --init-temp 30
python -m adapters.mqtt_adapter.sim_ac --broker mqtt://broker.emqx.io:1883
python -m web.audit_dashboard --hub http://127.0.0.1:18423 --port 18080

# 工作流调用（MCP）
python -c "import httpx,json; r=httpx.post('http://127.0.0.1:18423/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'run_workflow','arguments':{'workflow':'office_cooling'},'caller':'demo','permission_level':'write'}});print(r.json()['result'])"
```
