# 阶段 2 过程证据（原始输出存档）

> 说明：以下为关键节点的真实运行输出（text-based evidence），
> 供研究报告"实验过程"与答辩 PPT 引用。截图/录屏可在此基础上补充。

## E1. 六类工具统一注册（Agent 视角 tools/list）

```
tools/list -> 6 个: ['git_status', 'file_search', 'get_weather',
                    'file_summary', 'get_temperature', 'get_humidity']
```
覆盖 4 类资源：CLI（git_status/file_search）、REST（get_weather）、
脚本（file_summary）、IoT（get_temperature/get_humidity）。

## E2. REST 适配器真实调用（open-meteo，北京）

```
get_weather -> isError=False latency=4664ms data=
{"latitude":39.89455,"longitude":116.35983,"generationtime_ms":0.10,
 "utc_offset_seconds":28800,"timezone":"Asia/Shanghai","timezone_abbreviation":"GMT+8",
 "elevation":47.0,"current_weather":{...}}
```
说明：OpenAPI Spec 导入 → 自动生成 MCP Tool → Agent 无差别调用。

## E3. 脚本适配器调用（file_summary，输出 JSON 结构化）

```
file_summary -> isError=False latency=115ms data=
{'count': 13, 'files': ['contracts.py', '__init__.py', 'gateway/server.py', ...]}
```

## E4. SQLite 持久化（tools + audit 表）

```
SQLite tools 表: 5 条 -> ['cli.git.status', 'cli.file.search', 'rest.open-meteo',
                         'script.file.summary', 'iot.temp_01']
SQLite audit 表: 2 条（最近 20）
示例: trace=d243104f tool=get_weather guard=passed latency=4664.0ms
```
注：iot.temp_01 为 MQTT 自动发现设备，同样持久化 → 设备能力注册可追溯。

## E5. 重启恢复（持久化验收）

```
== RESTART CHECK START ==
重启后 tools/list -> 6 个: ['git_status', 'file_search', 'get_weather',
                          'file_summary', 'get_temperature', 'get_humidity']
== RESTART CHECK DONE ==
```

## E6. 审计样例（data/audit.jsonl，双写）

```json
{"trace_id": "3d305512", "ts": "...", "caller": "e2e_mqtt", "tool": "get_temperature",
 "args": {}, "guard_result": "passed", "result": {"ok": true}, "latency_ms": 0}
{"trace_id": "96208284", "ts": "...", "caller": "e2e_mqtt", "tool": "get_temperature",
 "args": {"room": "livingroom"}, "guard_result": "blocked",
 "block_reason": "未知参数: room", "result": {"ok": false}, "latency_ms": 0}
```
