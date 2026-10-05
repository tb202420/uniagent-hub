# 阶段 2 测试报告

> 日期：2026-09-25 · 范围：SQLite 持久化 / REST 适配器 / 脚本适配器 / 契约测试 / E2E
> 运行环境：Windows，Python 3.14（.venv），公共 MQTT broker（broker.emqx.io）

## 一、测试结果汇总

| 项 | 结果 | 说明 |
|---|---|---|
| 单元/集成测试 | **79 passed** | SQLiteStore / OpenAPI 解析 / REST 适配器（mock）/ 脚本适配器 / 契约测试 / 既有 47 项无回归 |
| CLI E2E | ✅ | git_status 93ms（阶段 1 复测无回归） |
| MQTT E2E | ✅ | get_temperature 24.9°C（阶段 1 复测无回归） |
| REST E2E | ✅ | get_weather 真实调用 open-meteo，返回北京天气 JSON |
| 脚本 E2E | ✅ | file_summary 115ms，返回 {"count":13, "files":[...]} |
| 持久化 | ✅ | SQLite tools 5 条（含自动发现 IoT）；audit 可查询 |
| 重启恢复 | ✅ | Hub 重启后 tools/list 仍为 6 工具 |

## 二、安全测试

| 用例 | 结果 |
|---|---|
| CLI 注入 `x; rm -rf /` | 1007 拦截 ✅ |
| REST 未知参数 `evil` | 1002 拦截 ✅ |
| Script 未知参数 `evil` | 1002 拦截 ✅ |
| 越权（read 调 write 级工具） | 1003 拦截 ✅ |
| SSRF：base_url 指向 127.0.0.1 / 192.168.* | 拦截并报 SSRF ✅ |
| API Key 从 env 注入 Header | 密钥不进参数/审计 ✅ |
| 响应 >1MB | 截断并标注 ✅ |
| 脚本路径 `../` 逃逸 | 注册阶段拒绝 ✅ |

## 三、性能观测

| 调用 | 延迟 |
|---|---|
| get_weather（首次冷调用，公共 API） | 4664ms |
| file_summary（本地脚本） | 115ms |
| git_status（本地 CLI） | 93ms |
| get_temperature（MQTT 缓存） | 0ms |
| SQLite audit 查询 | <10ms（本地） |

说明：get_weather 首次调用为公共 API 冷启动（含 TLS 握手），演示时可预热或本地 Mock 兜底；
其余本机链路均满足验收标准（CLI<200ms、MQTT<500ms）。

## 四、复现命令

```bash
# 全量测试
python -m pytest tests/ -q

# 启动 Hub（CLI+REST+Script+MQTT），另起终端：
python main.py --port 18423
python -m adapters.mqtt_adapter.simulator --broker mqtt://broker.emqx.io:1883

# 演示 Agent
python -m agent.demo_agent --url http://127.0.0.1:18423
```
