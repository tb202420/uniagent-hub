# UniAgent Hub — 5 分钟演示脚本

> 版本：v1.3 · 日期：2026-10-04 · 目标：**9/9 基线（含 ESP32 温室模拟器）+ LLM 加演（可选）全绿**
> 主线：开场 → 工具列表（演示档 14 工具，全量 22）→ 脚本工作流闭环 → **ESP32 温室灌溉闭环（模拟器）（核心亮点）** → 安全拦截 → CLI 反向生成 → 审计界面 → 收尾
> v1.3 变更：第四幕由 LLM 改为 **ESP32 温室灌溉（模拟器）**（与演示视频 v2 分镜、答辩 PPT v2 对齐）；
> 工具数 9 → **14**（演示档 = 软件档 11 + 温室模拟节点 3；全量 22 另含硬件档 8）；LLM 自主决策移为**加演环节**（§11 备查不删）；
> 评分表基线由 8 项改 9 项（新增模拟器项）。
> v1.2 变更：新增第四幕 LLM 自主决策；`demo_start.ps1` 新增 `-Ollama` 一键预热。
> v1.1 变更：演示端口固定 **8020**；P1-P6 一键自动化。

### 幕次编号对照（v1.2 → v1.3，供历史彩排记录对照）

| v1.2 | v1.3 | 说明 |
|---|---|---|
| 第一幕 开场 | 第一幕 开场（架构图） | 不变 |
| 第二幕 工具发现 | 第二幕 工具列表（演示档 14 工具） | 工具数更新 |
| 第三幕 脚本工作流闭环 | 第三幕 脚本工作流闭环 | 不变 |
| **第四幕 LLM 自主决策** | **第四幕 ESP32 温室灌溉闭环（模拟器）** | **v1.3 核心变更；LLM 移为加演** |
| 第五幕 安全演示 | 第五幕 安全拦截 | 不变 |
| 第六幕 CLI 反向生成 | 第六幕 CLI 反向生成 | 不变 |
| 第七幕 审计界面 + 收尾 | 第七幕 审计界面 + 第八幕 收尾 | 拆分与 v2 视频分镜对齐 |

> 已完成的 3 次彩排（`docs/test-reports/demo_rehearsal_log.md`，均 8/8）对应 v1.1/v1.2 结构；
> v1.3 新增模拟器项后基线为 9 项，需按新结构重新彩排。

---

## 0. 演示前准备（P1-P7，一条命令完成）

```powershell
# 演示含 LLM 环节（推荐）：一键拉起全栈 + 预热本地模型
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Ollama

# 断网 / 公共 API 不稳定时（本地 broker + 本地 Mock 天气 API + LLM 预热）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -Ollama

# 彩排 / 无人值守（日志落 logs/*.log，不弹控制台窗口）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -Ollama -LogToFile

# 不含 LLM 环节时（8/8 基线）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1
```

脚本自动完成 P1-P7，**无需任何手动配置**：

| # | 环节 | 脚本动作 | 就绪判据 |
|---|---|---|---|
| P1 | 启动 Hub 核心 | `main.py --port 8020` | `GET /healthz` 返回 `status=ok` |
| P2 | 温度模拟器 | `simulator --init-temp 31` | `get_temperature` 可返回数值 |
| P3 | 空调 / 温室模拟器 | `sim_ac` + `sim_esp32_greenhouse --init-soil 25`（订阅命令 topic + 发布 retain 初始状态） | `get_ac_state` / `get_soil_moisture` 可返回状态 |
| P4 | **预热 REST** | 调 `get_weather` 两次（首次冷连接约 4-5s，第二次命中 300s 缓存） | 第二次调用 < 100ms |
| P5 | 审计面板 | `web.audit_dashboard --hub ...8020 --port 18080` | http://127.0.0.1:18080 可打开 |
| P6 | 就绪自检 | `scripts/demo_warmup.py` 汇总 5 项检查 | 输出"全部就绪，可以开始演示" |
| P7 | **预热本地 LLM** | `scripts/ollama_warmup.py`（`-Ollama`）：检查服务/模型 → 按 `num_ctx=16384` 加载权重 → `keep_alive=-1` 常驻 | 汇总表出现 `ollama_llm 11434 已预热` |

固定演示参数（勿改）：

- **端口 8020**（Hub）/ **18080**（审计面板）/ 11434（Ollama）/ 1883、8899（仅离线模式）
- **`--init-temp 31`**：温度必须 > 28°C 才能确定触发 `office_cooling` 工作流；
- **`get_weather` 必须预热**：否则工作流第 2 步现场等 4-5 秒，观感像卡死；
- **`num_ctx` 必须是 16384**：Ollama 默认只加载 4096，会截断提示词；
  **勿设 `OLLAMA_CONTEXT_LENGTH=65536`**（本机 16GB 显存会被挤爆，首次请求 >300s 超时）；
- **LLM 幕非必需**：未接 LLM 时仍可完成 8/8 基线演示（§11 第 9 项不计）。

> 启动失败时：`logs/hub.log`、`logs/sim_temp.log`、`logs/sim_ac.log`、`logs/sim_esp32.log`、`logs/dashboard.log`。
>
> **现场纪律**：Ollama 不可并发调用（服务串行排队，并发会导致超时）；
> 演示前确认 Ollama 桌面版已关闭自动更新（脚本会提醒）。

---

## 1. 时间分配总表（5 分钟 = 300s）

| 时间 | 幕 | 内容 | 模式 | 主打 |
|---|---|---|---|---|
| 0:00-0:30 | 一 | 开场：架构图 + "AI 世界的 USB-C" | — | 定位 |
| 0:30-1:00 | 二 | 工具列表：Dashboard 展示 **14 工具**（演示档 = 软件档 11 + 温室模拟节点 3） | — | 一规范多类型 |
| 1:00-1:40 | 三 | **脚本工作流闭环**：office_cooling 三步 | 脚本 | **稳定** |
| 1:40-2:40 | 四 | **ESP32 温室灌溉闭环（模拟器）**：smart_irrigation（土壤 25% → 自动开泵） | 模拟器 | **模拟器实证** |
| 2:40-3:30 | 五 | 安全拦截：注入/越权/限流 + 审计高亮 | — | **安全内建** |
| 3:30-4:00 | 六 | CLI 反向生成：`gen_get_temperature.py` | — | 一规范双向 |
| 4:00-4:30 | 七 | 审计界面：完整调用链路查询 | — | 可观测 |
| 4:30-5:00 | 尾 | 收尾：四大创新 + 一键部署 + 降级结论 | — | 工程完备 |

> LLM 自主决策（v1.2 第四幕）移为**加演环节**：时间充裕或评委感兴趣时在收尾后加演
> （命令见 §11），主线不含、失败不扣基线分。

## 2. 第一幕：开场（0:00-0:30）

开场白：**"AI 世界的 USB-C 接口"** —— 温度传感器、空调、Git、天气 API、本地脚本，
五种完全不同的资源，Agent 眼里只有一份统一的 `tools/list`。

> 30 秒内讲完"为什么需要统一接入层"：现在每接一个新工具都要改 Agent 代码，
> UniAgent Hub 把这件事变成"注册一份 UniSpec"。

## 3. 第二幕：统一工具发现（0:30-1:00）

```powershell
python -m agent.llm_agent --script --url http://127.0.0.1:8020
```

面板同步展示：http://127.0.0.1:18080 概览页列出演示档全部已注册工具 ——
**14 个工具**（演示档 = 软件档 11：IoT 4 / CLI 2 / REST 1 / 脚本 1 / 数据库 2 / 工作流 1；
温室模拟节点 3：土壤湿度 / 光照 / 水泵），全量 22 另含硬件档 8（摄像头 2 / 智能插座 2 / 手机节点 2 / PC 监控 2），
观看者无法从工具名区分背后是 MQTT 设备、数据库还是真实硬件；
各档工具命名空间与限流配额隔离，物理执行类能力一律 write + 回执 + 时长上限。

## 4. 第三幕：脚本工作流闭环（1:00-1:40）

工具面板逐个调用（或用脚本模式输出）：

1. `get_temperature` → **约 31°C**（IoT，MQTT 状态缓存，毫秒级）
2. `git_status` → 仓库状态（CLI，subprocess 沙箱）
3. `get_weather` → 天气（REST，缓存命中 **0ms**）
4. **重头戏**：`run_workflow("office_cooling")`，一次调用完成 3 步闭环：
   `31°C → 查天气 → 空调 on 29°C`（约 1-4s，**空调模拟器窗口同步打印收到命令**）

> 讲解点：Agent 只发一次调用，工作流引擎完成拓扑排序、数据管道
> （`{{s1.output}}`）、失败传播 —— 每一步仍逐个过 Guard，安全不旁路。
> **这一幕主打稳定**：确定性脚本模式，零外部依赖、结果可复现。

## 5. 第四幕：ESP32 温室灌溉闭环（模拟器）（1:40-2:40）★ 核心亮点

**准备（已由 `demo_start.ps1` 自动完成）**：温室模拟器 `sim_esp32_greenhouse`
（`--init-soil 25`，broker `mqtt://127.0.0.1:1883`）已连入 broker；其控制台显示
UniSpec 注册（retain）与 30s 周期上报；`tools/list` 已出现 `iot.irrigation_01.*`
三个工具；土壤湿度 25%（< 30）满足浇水条件。

**操作**：①号终端运行预先粘贴的触发命令（等同
`tools/call run_workflow {"name":"smart_irrigation"}`），执行时切到 **③号温室模拟器窗口**
（观察命令回执日志）。

**画面关键行**：
```
s1 get_soil_moisture   → 25%（< 30 阈值）      0ms（缓存）
s2 get_light_intensity → 12123.5 lux           0ms（缓存）
s3 control_pump(action=on, duration=300) → 回执确认（100ms）✓
模拟器：[sim_irrigation] 命令 {'action':'on',...} -> 水泵 on   ← 土壤湿度回升
```

**关键讲解点（这段是 v1.3 的核心武器）**：

1. **Python MQTT 模拟器复现传感器读数与水泵回执**：温室节点模拟器暴露土壤湿度 /
   光照强度读数与水泵开关能力，走 MQTT，30s 周期上报（真机固件骨架已预留
   `docs/hardware/firmware/esp32/`，当前以模拟器为准，未烧录）；
2. **零配置接入**：设备端只发布一份 UniSpec（retain），平台自动发现并生成 3 个工具
   （上线到出现在 tools/list 约 0.23s）—— 对照上一届"每个数据点在平台手工配置"的直接进步；
3. **一次调用完成闭环**：1.30 秒完成读土壤 → 读光照 → 条件判断 → 开泵；写操作有 QoS1 回执、
   幂等重试与 600s 时长上限，物理执行类工具与软件档**档位隔离**；
4. **模拟器如实复现的协议细节**：写回执按 `request_id` 精确匹配（避免陈旧回执误判）、
   浇水后土壤湿度回升（复现真实设备的读数爬升行为）、单次运行超 600s 到点自动停泵
   —— "模拟器复现协议与回执，真机固件骨架已预留"；
5. **降级预案**：模拟器进程未启动时可重启 `sim_esp32_greenhouse`，
   或改播 `demo_fallback/03b_esp32_irrigation.mp4` 继续演示。

## 5b. 加演环节：LLM 自主决策（可选，不占 5 分钟主线）

```powershell
python -m agent.llm_agent --ollama --url http://127.0.0.1:8020 --goal "会议室太热了，帮我降温到 26 度"
```

本地部署的 Gemma-4-26B 量化模型**自主决策**：先调 `get_temperature` 拿到实测温度，
**看到结果后**再决定调用 `ac_control`，最后中文总结 —— 真实 ReAct 闭环，实测 3 轮 15-25s。

**加演讲解点**：真 AI 不是脚本（无硬编码调用顺序）；LLM 只负责"决策"、安全不依赖 LLM
可靠性（所有调用必经 Guard）；主动展示三级降级链（原生 tool_calls → 提示词计划 → 确定性
脚本）；主动说明 3-bit 量化 ±1°C 数值转述边界。技术细节与实测数据见 §11。

## 6. 第五幕：安全演示（2:40-3:30）

1. **命令注入**：`file_search(pattern="x; rm -rf /")` → **1007 拦截**
2. **越权调用**：`ac_control(action="on")` 以 read 权限 → **1003 拒绝**
   （对比：`get_ac_state` 同一设备、read 权限 → 放行，能力级权限粒度）
3. **超限触发**：连续快速调用同一工具 → **1004 限流**

> 讲解点：无论调用方是 LLM 还是脚本，Guard 管道一视同仁；
> 被拦截请求的完整参数全部落审计，事后可追溯。

## 7. 第六幕：CLI 反向生成（3:30-4:00）

```powershell
python generated_cli\gen_get_temperature.py
```

> 讲解点：注册中心里的 UniSpec 不仅能正向生成 MCP Tool，
> 还能反向生成人类可用的 CLI 脚本（`generated_cli/` 共 8 个）——
> 同一份能力描述，两个消费方向，这是"一规范多类型"的直接收益。

## 8. 第七幕：审计界面（4:00-4:30）

浏览器 http://127.0.0.1:18080 ：

- **审计页**：刚才所有调用（含被拦截的 1007/1003/1004）按时间倒序，
  可按 caller / 工具筛选；
- **工作流页**：`office_cooling` 各步骤状态与耗时（s1/s2/s3 全 ok）；
- 每步都有 `trace_id`，从 Agent 到设备全链路可追溯。

## 9. 收尾（4:30-5:00）

一句话收束：**"22 个工具全量（演示档 14）、5 类资源来源 + 4 类真实硬件 + 1 类模拟器节点、一份规范；安全内建、无状态网关、
三级降级、模拟器在环 —— 这就是 UniAgent Hub。"**

> 若被问到"如果现场断网/模型挂了/模拟器不响怎么办"：**一键 `-Offline` 重启**（本地 broker + Mock API，
> 核心功能完全不变）+ **LLM 三级降级链** + **温室兜底视频 `03b_esp32_irrigation.mp4`** +
> **预录视频兜底**（`demo_fallback/`）。这本身就是工程完备性的体现。

---

## 10. 降级方案（现场异常时切换）

| 异常 | 现象 | 处置 |
|---|---|---|
| 断网 / 公共 API 不通 | get_weather 超时、MQTT 无消息 | 改用 `-Offline` 重启：本地 amqtt + Mock API（核心功能不变） |
| 公共 broker 抖动 | 模拟器/Hub 无消息 | 重启模拟器窗口（retain 注册消息自动重新注册，Hub 无需重启） |
| open-meteo 超时 | get_weather 报错 | 预热缓存可撑 300s；否则跳过该步，工作流仍可单独演示 |
| 温度未触发工作流 | ≤28°C | 用 `--init-temp 31` 重启模拟器（准备阶段已规避） |
| **本地模型未就绪** | LLM 加演调用报连接失败 | `demo_start.ps1 -Ollama` 汇总表会显示 `ollama_llm 未就绪(降级)`；Agent 自动降级（三级链），**照常加演并当场说明降级机制**；主线不含 LLM，不影响 9/9 基线 |
| **LLM 请求超时** | 单轮等待明显变长 | 默认 60s 超时后自动降级；可 `--timeout 30` 缩短等待 |
| **正被其他进程占用 GPU** | 模型响应变慢 | 关闭占用显存的程序（浏览器/游戏）；Ollama 串行排队，勿并发调用 |
| **温室模拟器未上线** | tools/list 缺硬件工具、模拟器幕无法演示 | 重启 `sim_esp32_greenhouse --init-soil 25`（retain 注册消息会自动重新发现，约 0.23s）；仍失败改播 `03b_esp32_irrigation.mp4`（核心兜底），继续后续幕 |
| **水泵不启动** | 回执超时或条件不满足 | 检查模拟器进程与初始土壤湿度参数（`--init-soil 25`，<30 才触发）；已内置 3s 回执 + 幂等重试 |
| 整机故障 | — | 播放 `demo_fallback/01_full_demo.mp4`（详见其 README） |

## 11. LLM 环节技术细节与实测数据（答辩备查）

>`5b 加演环节`的执行机制、实测结论与限项——答辩被追问时翻这一节。

**三级降级链**（演示永不中断）：
原生 `tool_calls`（ReAct 闭环）→ 提示词 JSON 计划 → 确定性脚本模式。

**本地模型实测结论与限项（2026-09-26，如实记录）**：

| 维度 | 实测结果 |
|---|---|
| 原生 tool_calls 通道 | 6/6 通过（含"双字符串参数""引号赋值"两个已知易错用例） |
| 演示目标端到端（temp=0.0） | 原生模式 5/5、动作正确 5/5、数值转述保真 4/5，均值 22.6s，无重复退化 |
| 条件分支用例（temp=0.0） | 原生模式 3/3、分支判断正确 3/3，均值 14.8s |
| 上下文窗口 | Ollama 默认仅 4096（模型原生 262144）→ 必须显式设置；**本机 65536 会挤爆显存**（16GB 卡占用 13.4GB、余 1.2GB，首次请求 >300s 超时），**16384 稳定** |
| 采样温度 | **必须用 0.0**：temp=0.3 时原生模式仅 3/5、数值保真 0/5（会编造数值、谎称已执行未执行的操作）；temp=0.0 提升到 5/5、4/5，代价是耗时 12.3s→22.6s |
| 单轮工具数 | 必须由代码强制串行（`MAX_CALLS_PER_ROUND=1`）——模型会在未观察结果前批量发调用，导致条件分支失效 |
| 输出长度 | 必须显式设 `num_predict`（原生通道无 `max_tokens` 默认值），否则退化生成可挂起 >120s |
| 并发请求 | Ollama 串行排队，**不可并发调用**（并发会超时） |
| 已知残余限项 | 偶发把 `31.0` 转述为 `30`（取整）；极少数轮次输出纯模板残留 token，此时自动降级 |

**云端 LLM 备选（DeepSeek / 百炼兼容模式）**：

```powershell
$env:LLM_API_KEY = "<DeepSeek/百炼 API Key>"
python -m agent.llm_agent --url http://127.0.0.1:8020 --goal "会议室太热了，帮我降温到 26 度"
```

调试工具：`scripts/ollama_tool_probe.py`（模型能力探针）、
`scripts/llm_stability_check.py`（批量稳定性评分，支持 `--expect-no-ac` 断言条件分支）、
`scripts/ollama_warmup.py`（预热）。
证据：`docs/evidence/README.md`（索引）、`docs/evidence/ollama_probe_1.json`、
`docs/evidence/llm_stability_final*/`、`docs/evidence/llm_stability_temp0/`。

---

## 12. 完整度评分表（9/9 基线 · 含 ESP32 温室模拟器 + 第 10 项 LLM 加演）

| # | 评分项 | 通过判据 | 检查方式 |
|---|---|---|---|
| 1 | P1-P7 就绪 | `demo_start.ps1` 输出"全部就绪"，warmup 检查全 ✓ | 启动脚本 stdout |
| 2 | 第二幕 工具列表 | `tools/list` 返回 **14** 个工具（演示档；全量 22） | Agent 输出 / 面板 |
| 3 | 第三幕 单工具三连 | `get_temperature`≈31°C、`git_status` ok、`get_weather` 0ms 缓存 | Agent 输出 |
| 4 | 第三幕 工作流闭环 | `office_cooling` 三步全 ok，且 **sim_ac 窗口打印收到命令** | Agent 输出 + sim_ac 日志 |
| 5 | **第四幕 ESP32 温室灌溉闭环（模拟器）** | `smart_irrigation` 三步全 ok；模拟器日志出现**水泵 on 命令回执**；工作流页含模拟器明细 | Agent 输出 + 模拟器日志 |
| 6 | 第五幕 安全三连 | **1007 + 1003 + 1004 全部命中** | 拦截返回码 |
| 7 | 第六幕 CLI 反向生成 | `gen_get_temperature.py` 实跑成功返回温度 | 脚本 stdout |
| 8 | 第七幕 审计可见 | 审计页含被拦截记录与模拟器调用；工作流页含 office_cooling / smart_irrigation 明细 | 浏览器/HTTP 抓取 |
| 9 | 时长与稳定性 | 全流程 **≤ 5 分钟** 且**无报错**（含无 traceback） | 计时 + 日志 |
| 10 | **LLM 自主决策（可选加演）** | P7 显示 `ollama_llm 已预热`；Agent 输出"原生 tool_calls 模式"且**由模型自主选出 `ac_control`**；结论数值与工具返回值一致（允许 ±1） | Agent stdout + 启动汇总表 |

**通过标准**：
- **基线：连续 3 次彩排均为 9/9**（模拟器幕失败时按预案改播兜底片段并如实说明，该项记降级通过）；
- 加演 LLM 按 **10 项**计分，第 10 项失败不扣基线分（降级链已兜底，仍算 9/9）。

彩排记录见 `docs/test-reports/demo_rehearsal_log.md`
（已有 3 次对应 v1.1/v1.2 结构的 8/8；v1.3 新结构需重新彩排）。

## 13. 演示前自检表（每次彩排过一遍）

- [ ] `demo_start.ps1 -Ollama` 返回"全部就绪"，warmup 检查全 ✓（加演时含 `ollama_llm 已预热`）
- [ ] 模拟器初始温度 31°C，`get_ac_state` 可返回
- [ ] **温室模拟器检查全过**（进程已启动 / broker 已连接 / 注册 retain / 30s 上报 / tools-list 硬件工具 / 初始土壤 25%）
- [ ] 8 幕全部走完无报错，计时 ≤ 5 分钟
- [ ] 9 项基线评分全部通过（加演时第 10 项亦通过）
- [ ] 连续 3 轮全绿（正式标准）
- [ ] Ollama 桌面版**自动更新已关闭**（避免后台下载导致服务重启）
- [ ] 预录视频可播放（`demo_fallback/`，含温室兜底 `03b_esp32_irrigation.mp4`）
