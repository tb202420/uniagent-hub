# demo_fallback —— 演示降级素材与应急预案

> 用途：当现场网络 / 公共 API / 设备模拟不可用时，**仍然能完整演示核心功能**。
> 目录中的视频文件（`*.mp4`）已被 `.gitignore` 忽略，需在赛前手动放入。

## 1. 目录约定

```
demo_fallback/
├── README.md                # 本文件（降级剧本 + 命名规范）
├── 01_full_demo.mp4         # 完整 5 分钟演示预录（整机故障时播放）※ 尚未录制
├── 02_second_act_tools.mp4     # 第二幕：tools/list 统一工具发现（14 工具演示档；全量 22）
├── 03_third_act_workflow.mp4   # 第三幕：单工具 + office_cooling 工作流闭环
├── 03b_esp32_irrigation.mp4    # 第四幕：ESP32 温室灌溉闭环（模拟器）（核心兜底）※ 尚未录制
├── 05_fifth_act_guard.mp4      # 第五幕：1007 注入拦截 / 1003 越权 / 1004 限流
├── 06_sixth_act_cli.mp4        # 第六幕：CLI 反向生成脚本实跑
└── 07_seventh_act_audit.mp4    # 第七幕：审计面板（含被拦截调用与错误码）

命名规范：`序号_幕名.mp4`，序号与演示脚本（v1.3 八幕）幕次一致；单个分幕视频 30-90 秒，
便于"只缺某一环"时定点补播，而不是整段重播。
（v1.1 旧命名如 `02_first_act_tools.mp4` 等，如已录制仍可作兜底使用。）

## 2. 预录视频录制要求

| 项 | 要求 |
|---|---|
| 录制方式 | **原始录屏，不剪辑**（与 `docs/demo_video_guide.md` 同一流程） |
| 分辨率 | 1920×1080，终端字号 ≥ 16pt（评委端可读） |
| 时长 | `01_full_demo.mp4` ≤ 5 分钟；分幕片段按幕时长 |
| 必含内容 | 每幕的关键输出行 + 设备模拟器窗口的同步打印（体现"多设备协同"） |
| 存放位置 | 本目录，文件名严格按上表 |

> 录制步骤见 `docs/demo_video_guide.md`（第三部分：预录素材录制）。

## 3. 降级决策树（现场 30 秒内完成切换）

```
演示出问题
├─ 只是网络不可用（公共 broker / open-meteo 不通）
│   → 用 -Offline 重启：本地 MQTT broker(amqtt) + 本地 Mock 天气 API
│      powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline
│   → 核心功能（工具发现/工作流闭环/安全拦截/审计）**完全不变**
│     差异仅：天气数值来自 mock（固定 26.0°C）、MQTT 不出本机
│
├─ 单个设备模拟器挂掉
│   → 仅重启该模拟器窗口（retain 注册消息会自动重新注册，Hub 无需重启）
│      python -m adapters.mqtt_adapter.simulator --init-temp 31
│      python -m adapters.mqtt_adapter.sim_ac
│
├─ Hub 进程崩溃
│   → 重新执行 demo_start.ps1（SQLite 会自动恢复工具与审计记录）
│
└─ 整机 / 投影 / 环境彻底不可用
    → 播放 demo_fallback/01_full_demo.mp4（讲解词照常，由视频画面承载）
       某一幕临时出问题 → 播放对应分幕片段 0X_*.mp4
```

## 4. 断网降级实测结论（详见 docs/test-reports/demo_rehearsal_log.md）

| 能力 | 在线模式 | 断网降级模式 | 是否等价 |
|---|---|---|---|
| tools/list（14 工具演示档发现） | ✅ | ✅ | 完全等价（工具名/Schema 一致） |
| get_temperature（MQTT） | ✅ 公共 broker | ✅ 本地 amqtt | 完全等价 |
| git_status / file_search / file_summary | ✅ 本地进程 | ✅ 本地进程 | 完全等价 |
| get_weather（REST） | ✅ open-meteo | ✅ 本地 mock（26.0°C） | 工具契约等价，数值固定 |
| run_workflow office_cooling | ✅ | ✅ | 完全等价（含 ac_control 写回执） |
| Guard 安全拦截（1007/1003/1004） | ✅ | ✅ | 完全等价（不依赖网络） |
| 审计面板 | ✅ | ✅ | 完全等价 |

**结论**：断网模式下"AI 世界的 USB-C 接口"的核心主张（统一抽象 + 安全内建 + 编排闭环）
可 100% 演示；仅天气来源由云端换为本地 mock，而这恰好是"Agent 只认识 MCP、
背后资源可替换"主张的最好证据。

## 5. 一键启动参数速查

```powershell
# 在线模式（默认，公共 broker + open-meteo）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1

# 断网降级模式（本地 broker + Mock API）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline

# 彩排 / 无人值守（写 logs/*.log，不弹窗口）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -LogToFile

# 自定义端口 / 初始温度 / 跳过面板
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Port 8030 -InitTemp 31 -NoDashboard
```
