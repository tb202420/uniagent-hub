# UniAgent Hub — 演示彩排记录（3 次独立彩排）

> 日期：2026-09-26 · 演示端口：**8020**（Hub）/ 18080（审计面板）
> 启动方式：`scripts/demo_start.ps1`（在线 / `-Offline` 断网降级两种模式）
> 评分标准：`docs/demo_script.md` §8 八项完整度评分表
> 原始证据：`docs/evidence/demo_rehearsal_1.txt` ~ `_3.txt`、`docs/evidence/demo_start_1.txt` ~ `_3.txt`
> 结果：**连续 3 次 8/8 全绿**

---

## 0. 预备轮（记作第 0 次）：暴露问题轮

第一次跑彩排脚本即暴露 2 个真实问题（**未计入 3 次正式彩排**，修复后重跑）：

| # | 类别 | 现象 | 根因 | 处置 |
|---|---|---|---|---|
| A | **产品缺陷** | `get_ac_state` 返回 `{'action': 'on', ...}`（Python repr，单引号），不是合法 JSON，`json.loads` 失败 | `core/gateway/server.py::_finish` 用 `str(result.data)` 序列化适配器返回的 dict | 新增 `_to_text()`：dict/list 走 `json.dumps(ensure_ascii=False)`，工具输出统一为 JSON 文本 |
| B | 彩排脚本缺陷 | 第二幕 `get_temperature` 返回空值、工作流校验拿不到空调状态，评分 6/8 | 彩排脚本多个环节复用同一 `caller`，撞上设备 1/s 限流（1004） | 各幕改用独立 caller（`rehearsal_ready` / `_act2` / `_wf` / `_ac`），与真实演示中各角色独立 caller 一致 |

> 问题 A 属于"专业演示级"必须修的类型：生成的 CLI 脚本与 Agent 都按 JSON 解析工具输出，
> Python repr 会让 `jq`/`json.loads` 直接失败。修复后 3 次正式彩排均通过。

---

## 1. 第 1 次彩排（离线降级模式）

**环境**
- 启动：`powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -LogToFile`
- 模式：断网降级 —— 本地 amqtt broker `mqtt://127.0.0.1:1883` + 本地 Mock 天气 API `http://127.0.0.1:8899`
- 端口：Hub 8020 / Dashboard 18080 / Broker 1883 / Mock 8899
- 启动证据：`docs/evidence/demo_start_1.txt`（pid 26480/24656/29088/1048/23428/37492）

**逐步实测结果（P1-P6）**

| 环节 | 结果 |
|---|---|
| P1 Hub 核心 | ✓ `/healthz` 返回 `{"status":"ok","tools":8}` |
| P2 温度模拟器 | ✓ `--init-temp 31`，实测 30.9°C |
| P3 空调模拟器 | ✓ `get_ac_state` 返回初始 `{"action":"off","temperature":26}` |
| P4 预热 REST | ✓ `get_weather` 第 1 次 0ms（本地 mock）/ 第 2 次 0ms |
| P5 审计面板 | ✓ http://127.0.0.1:18080 可访问 |
| P6 就绪自检 | ✓ `demo_warmup` 输出"全部就绪，可以开始演示" |

**五幕实测**

- 第一幕：`tools/list` = 9 工具（git_status, file_search, get_weather, file_summary, get_ac_state, ac_control, get_temperature, get_humidity, run_workflow）
- 第二幕：`get_temperature` 30.9(0ms) | `git_status` ok(64ms) | `get_weather` 0ms 缓存；
  工作流 `office_cooling` s1/s2/s3 全 ok，设备回执 `ac_action=on, ac_temp=28`
- 第三幕：1007 注入拦截 ✓ / 1003 越权拒绝 ✓ / 1004 限流（序列 `[0,1004,1004]`）✓
- 第四幕：`gen_get_temperature.py` rc=0 输出 `30.9`
- 第五幕：审计页含 `blocked` 行 ✓；工作流页含 `office_cooling` 明细 ✓

**问题清单**

| # | 级别 | 问题 | 状态 |
|---|---|---|---|
| 1 | 提示 | 首次彩排前 1883 端口被上一会话残留的 amqtt broker 占用，启动脚本端口预检直接拦下并给出处置命令 | 已按提示停进程；**预检逻辑符合预期，不修改** |
| 2 | 提示 | 本机演示前 `logs/` 日志目录不存在 | `-LogToFile` 会自动创建，无需处理 |

**评分：8/8**（总耗时 3.8s，无报错）

---

## 2. 第 2 次彩排（在线模式：公共 broker + open-meteo）

**环境**
- 启动：`powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -LogToFile`
- 模式：在线 —— 公共 broker `mqtt://broker.emqx.io:1883` + 真实 `https://api.open-meteo.com`
- 启动证据：`docs/evidence/demo_start_2.txt`（pid 35308/26304/3196/9036）

**逐步实测结果（P1-P6）**

| 环节 | 结果 |
|---|---|
| P1 Hub 核心 | ✓ `{"status":"ok","tools":8}` |
| P2 温度模拟器 | ✓ 实测 30.7~30.8°C（公共 broker 往返正常） |
| P3 空调模拟器 | ✓ 初始 `{"action":"off","temperature":26}` |
| P4 预热 REST | ✓ 冷连接 **1621ms** → 第 2 次 **0ms**（300s 缓存生效，现场不会卡顿） |
| P5 审计面板 | ✓ |
| P6 就绪自检 | ✓ 全部就绪 |

**五幕实测**

- 第一幕：9 工具 ✓
- 第二幕：30.8(0ms) | git_status ok(58ms) | get_weather 0ms 缓存；
  `office_cooling` 三步全 ok（s2 真实天气：北京 39.89/116.36，**21.9°C**），
  设备回执 `ac_action=on, ac_temp=28`（s3 耗时 602ms，含公共 broker 往返）
- 第三幕：1007 ✓ / 1003 ✓ / 1004 序列 `[0,1004,1004]` ✓
- 第四幕：`gen_get_temperature.py` rc=0 输出 `30.8`
- 第五幕：审计页 blocked ✓ / 工作流页 office_cooling ✓

**问题清单**

| # | 级别 | 问题 | 状态 |
|---|---|---|---|
| 1 | 无 | 无功能性问题；在线模式全链路（真实公网 API + 公共 broker）通过 | — |

**评分：8/8**（总耗时 4.4s，无报错）

---

## 3. 第 3 次彩排（离线降级模式复测）

**环境**
- 启动：`powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -LogToFile`
- 模式：断网降级（本地 broker + Mock API），验证结果可复现性
- 启动证据：`docs/evidence/demo_start_3.txt`（pid 13044/16676/14452/4976/19052/1140）

**逐步实测结果（P1-P6）**：P1-P6 全部 ✓（温度 30.9°C；`get_weather` 两次均 0ms）

**五幕实测**

- 第一幕：9 工具 ✓
- 第二幕：30.9(0ms) | git_status ok(68ms) | get_weather 0ms；
  `office_cooling` s1/s2/s3 全 ok，天气读数固定 **26.0°C**（Mock 契约值），
  设备回执 `ac_action=on, ac_temp=28`
- 第三幕：1007 ✓ / 1003 ✓ / 1004 序列 `[0,1004,1004]` ✓
- 第四幕：`gen_get_temperature.py` rc=0 输出 `30.9`
- 第五幕：审计页 blocked ✓ / 工作流页 office_cooling ✓

**问题清单**

| # | 级别 | 问题 | 状态 |
|---|---|---|---|
| 1 | 无 | 与第 1 次结果一致（同温度区间、同拦截码、同延迟量级），可复现性确认 | — |

**评分：8/8**（总耗时 4.4s，无报错）

---

## 4. 汇总

| 彩排 | 模式 | 时长 | 完整度 | 阻断问题 |
|---|---|---|---|---|
| 第 0 次（预备） | 离线 | — | 6/8 | 2（1 产品 + 1 脚本）→ 已修复 |
| 第 1 次 | 离线（本地 broker + Mock API） | 3.8s | **8/8** | 0 |
| 第 2 次 | 在线（公共 broker + open-meteo） | 4.4s | **8/8** | 0 |
| 第 3 次 | 离线（复测） | 4.4s | **8/8** | 0 |

**结论：连续 3 次彩排均 8/8，达成验收标准。**

> 说明：表中"时长"为 `demo_rehearsal.py` 完成五幕的机器实测耗时（不含人工讲解）；
> 人工 5 分钟讲解节奏见 `docs/demo_video_guide.md` 的时间分配表。

## 5. 复现方式

```powershell
# 1) 一键启动全栈（P1-P6）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -LogToFile
# 2) 跑五幕 + 自动评分（真实证据）
python -m scripts.demo_rehearsal --label "复现"
# 输出末尾 "完整度评分：8/8" 且退出码 0 即为通过
```
