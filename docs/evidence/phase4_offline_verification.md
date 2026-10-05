# 阶段 4 证据：断网降级模式可用性验证

> 日期：2026-09-26 · 目的：证明**断网环境（无公共 broker、无公网 API）下核心演示功能完全可用**
> 相关：`demo_fallback/README.md`（降级剧本）· `docs/test-reports/demo_rehearsal_log.md`（第 1、3 次彩排即离线模式）

## 1. 降级方案构成

| 外部依赖 | 在线模式 | 断网降级模式 | 实现 |
|---|---|---|---|
| MQTT Broker | `mqtt://broker.emqx.io:1883`（公网） | `mqtt://127.0.0.1:1883` | `scripts/dev_mqtt_broker.py`（amqtt 0.12.1，纯 Python）|
| 天气 API | `https://api.open-meteo.com` | `http://127.0.0.1:8899` | `scripts/mock_weather_api.py`（stdlib，零依赖，固定 26.0°C）|
| 其余工具 | 本地进程 | 本地进程 | 无差异（git_status / file_summary / 工作流 / Guard / 审计）|

启用方式：`scripts/demo_start.ps1 -Offline`，自动注入三个环境变量：

```
HUB_MQTT_BROKER=mqtt://127.0.0.1:1883
HUB_REST_BASE_URL_OVERRIDE=http://127.0.0.1:8899
HUB_REST_ALLOWED_PRIVATE_HOSTS=127.0.0.1     # SSRF 白名单逃生舱（仅精确主机名，默认空=全拦）
```

## 2. 进程级证据（所有依赖均在 127.0.0.1）

`Get-CimInstance Win32_Process` 实测命令行（离线演示栈）：

```
13044  python -u -m scripts.dev_mqtt_broker --port 1883
16676  python -u -m scripts.mock_weather_api --port 8899
14452  python -u main.py --port 8020
4976   python -u -m adapters.mqtt_adapter.simulator --broker mqtt://127.0.0.1:1883 --init-temp 31
19052  python -u -m adapters.mqtt_adapter.sim_ac   --broker mqtt://127.0.0.1:1883
1140   python -u -m web.audit_dashboard --hub http://127.0.0.1:8020 --port 18080
```

→ 无任何进程引用公网主机名。

## 3. 天气数据来源指纹（证明走的是本地 Mock 而非公网）

同一次演示中，两种模式的 `get_weather` 回包对比：

| 字段 | 在线（真实 open-meteo） | 断网降级（本地 Mock） |
|---|---|---|
| `generationtime_ms` | `0.14269351959228516` | `0.12`（Mock 硬编码常量） |
| `utc_offset_seconds` | `0`（返回 GMT） | `28800`（Mock 固定 CST） |
| `current_weather.temperature` | `21.9`（实时值） | `26.0`（Mock 固定值） |
| `elevation` | `47.0` | `44.0` |
| 坐标回显 | `39.89455 / 116.35983`（服务端网格化） | `39.9042 / 116.4074`（原样回显） |

断网模式实测回包：

```json
{"latitude": 39.9042, "longitude": 116.4074, "generationtime_ms": 0.12,
 "utc_offset_seconds": 28800, "timezone": "Asia/Shanghai", "timezone_abbreviation": "CST",
 "elevation": 44.0, "current_weather": {"temperature": 26.0, "windspeed": 9.4, ...}}
```

本地 Mock 服务访问日志（证明 Hub 的 REST 适配器确实请求了本地服务）：

```
[mock-weather] 已启动 http://127.0.0.1:8899/v1/forecast（固定 26.0°C，Ctrl+C 退出）
[mock-weather] "GET /v1/forecast?latitude=39.9042&longitude=116.4074&current_weather=true HTTP/1.1" 200 -
```

## 4. 功能等价性验证（断网模式彩排实测）

断网模式下完整跑通五幕，结果与在线模式一致（详见 `demo_rehearsal_1.txt` / `demo_rehearsal_3.txt`）：

| 能力 | 断网模式实测结果 |
|---|---|
| tools/list 统一发现 | ✓ 9 个工具（工具名 / inputSchema 与在线模式完全一致） |
| get_temperature（MQTT 设备） | ✓ 30.9°C，0ms（本地 amqtt broker 往返） |
| git_status / file_summary（CLI / 脚本） | ✓ 68ms / 65ms（本地进程，与网络无关） |
| get_weather（REST） | ✓ 0ms（本地 Mock，且 300s 缓存仍生效） |
| run_workflow office_cooling | ✓ s1/s2/s3 全 ok，设备回执 `action=on, temperature=28` |
| Guard 安全三连 | ✓ 1007 注入拦截 / 1003 越权拒绝 / 1004 限流（与网络无关） |
| 审计面板 | ✓ 含 blocked 记录与 office_cooling 明细 |
| **完整度评分** | **8/8**（第 1、3 次彩排均为断网模式，均 8/8） |

## 5. 安全边界（降级不削弱防护）

SSRF 白名单逃生舱设计为**最小放行**：

- `HUB_REST_ALLOWED_PRIVATE_HOSTS` 默认**空**（维持全拦私有/保留网段），仅在 `-Offline` 时由启动脚本注入 `127.0.0.1`；
- 放行规则是**精确主机名匹配**，不是网段放行；
- 未声明的私有地址仍被拦截：`tests/unit/test_rest_adapter.py::test_ssrf_blocks_private_server`（127.0.0.1:8080）与 `test_ssrf_blocks_private_ip_literal`（192.168.1.5）在默认环境下行为不变，全量回归保持通过。

## 6. 结论

断网降级模式下，"AI 世界的 USB-C 接口"的四个核心主张
（一规范多类型 / Agent 只认识 MCP / 安全内建 / 能力双向）**可 100% 演示**；
唯一差异是天气数值来源从公网换为本地 Mock —— 而这恰好反向印证了
"Agent 只认识 MCP、背后资源可替换"这一核心设计：**工具契约不变，实现可换**。
