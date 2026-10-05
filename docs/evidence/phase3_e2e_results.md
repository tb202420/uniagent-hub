# 阶段 3 过程证据（原始输出存档）

> 说明：关键节点真实运行输出，供研究报告"实验过程"与答辩引用。

## E1. 9 工具统一注册（含内置 run_workflow）

```
tools/list -> 9 个: ['git_status', 'file_search', 'get_weather', 'file_summary',
                    'get_ac_state', 'ac_control', 'get_temperature',
                    'get_humidity', 'run_workflow']
```

## E2. 工作流一次调用闭环（office_cooling）

```
当前温度: 29.9
run_workflow(office_cooling) ...
workflow ok=True 总耗时=3969ms
  step s1 get_temperature -> ok output=29.9 latency=0ms
  step s2 get_weather -> ok output={北京天气 JSON} latency=2850ms
  step s3 ac_control -> ok output={'action': 'on', 'temperature': 27,
                                    'ts': '...', 'request_id': '...'} latency=1104ms
```
说明：Agent 只消耗一次调用 token 完成"测温 → 天气 → 开空调"；
数据管道 `{{s1.output}} - 2`（29.9-2=27.9→27），条件 `29.9 > 28` 触发。

## E3. 限流（Guard v2，1004）

```
限流演示: 连续调用 ac_control ...
第 6 次被限流 1004: [error 1004] 超出速率限制 5/m
                  （tool=ac_control, caller=p3_limit, scope=external）
```

## E4. CLI 反向生成（双向能力）

```
CLI 生成 8 个脚本 -> generated_cli
  - gen_git_status.py / gen_file_search.py / gen_get_weather.py
  - gen_file_summary.py / gen_get_ac_state.py / ...
gen_get_temperature.py 运行: rc=0 out=28.6
```
说明：MCP Tool → CLI 脚本，与 tools/call 等价，两种模式无缝切换。

## E5. 审计 Web 界面

```
GET / -> HTTP 200, 长度 1835      （概览：工具数/成功率/平均延迟）
GET /audit -> HTTP 200, 长度 8025 （分页筛选表格）
GET /workflows -> HTTP 200, 长度 1956（工作流执行链路）
```

## E6. 审计样例（工作流每步均入审计，Guard 不旁路）

```json
{"trace_id":"...", "caller":"p3", "tool":"get_temperature", "guard_result":"passed", ...}
{"trace_id":"...", "caller":"p3", "tool":"ac_control", "guard_result":"passed", ...}
{"trace_id":"...", "caller":"p3", "tool":"run_workflow", "guard_result":"passed", ...}
```
