# 演示操作手册（v3.0 · 1 页纸）

## 0. 准备（30 秒）

```powershell
# 全部命令在仓库根目录执行；务必用 .venv 的真实解释器
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

> 设备模式说明：默认演示启动 **SIL 模拟器**（`sim_esp32_greenhouse`），
> 终端与日志都会打印「设备模式：SIL（模拟器，非真机）」。
> 不要把模拟器的 100–141ms 说成真机 152ms（定义见 `docs/口径速查表.md` §6.3）。

## A. 正常流程（一键闭环，约 11 秒）

```powershell
.\.venv\Scripts\python.exe -m demo.irrigation_approval
```

脚本自动完成：

1. 起本地 MQTT Broker（127.0.0.1:1884）与温室模拟器（初始土壤 25% → 触发浇水）；
2. 起 Hub（127.0.0.1:8021，演示库/审计隔离在 `data/demo_irrigation.db`）；
3. 通过 `/agent/run` 让 script Agent 生成计划（13 个 `agent.token` 事件）；
4. 读土壤湿度（<30）→ 读光照 → 调 `control_pump`；
5. Guard 触发 HITL 审批，事件流推送 `hitl.request`，脚本停留 2s 后批准；
6. MQTT 命令下发，模拟器回执；最后校验审计哈希链。

预期输出（关键 5 处）：

- `[demo] 设备模式：SIL（模拟器，非真机）`
- `[approver] 收到审批请求：AI 想启动水泵 300 秒，是否允许？`
- `[executing] control_pump` → `[result] control_pump 100ms`
- `[demo] 审批等待 ~3.0s` · `[demo] 工作流耗时 ~5.2s`
- `[demo] 审计链: ok`

## B. 离线兜底流程（无真机 / 真机掉线）

```powershell
.\.venv\Scripts\python.exe -m demo.irrigation_approval --real --device-timeout 8
```

- 前 8 秒等待真机上线；
- 超时后自动启动模拟器，打印 **「已切换模拟设备（SIL 兜底）」**，演示继续；
- 日志中的 `device_mode` 会写成 `SIL（真机离线兜底）`，不会冒充 HIL。

## B2. 本地 Ollama Agent（大模型自主决策 · 视频主演示）

```powershell
# 0) 启动模型服务（默认 11434；本机被系统排除范围占用时改用 11500）
$env:OLLAMA_HOST = '127.0.0.1:11500'
& 'C:\Users\admin\AppData\Local\Programs\Ollama\ollama.exe' serve   # 另开后台

# 1) 项目访问地址 + 预热（冷加载约 90s，必须提前做）
$env:OLLAMA_BASE = 'http://127.0.0.1:11500'
.\.venv\Scripts\python.exe -m scripts.ollama_warmup --model gemma4local:latest --num-ctx 16384

# 2) 演示：允许 / 拒绝 / 改 60 秒 / 真机优先
.\.venv\Scripts\python.exe -m demo.irrigation_approval --agent ollama
.\.venv\Scripts\python.exe -m demo.irrigation_approval --agent ollama --decision rejected
.\.venv\Scripts\python.exe -m demo.irrigation_approval --agent ollama --decision modify
.\.venv\Scripts\python.exe -m demo.irrigation_approval --agent ollama --real --device-timeout 8
```

- 模型只做决策（调用哪个工具、什么参数），`control_pump` 仍需**人工审批**；
- 模型未就绪/退化时改回默认 `--agent script`（三级降级，演示不失真）;
- 实测数据（2026-11-12）见 `docs/demo_video_guide.md` 附一与 `docs/口径映射表.md` §2b；
  模型决策耗时与 script 口径（10.8–11.1s）不同，**不要混说**。

## C. 手动演示（评委自己点审批）

```powershell
# 终端 A：一键起全栈（Hub 8020 + Dashboard 18080 + 模拟器）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1

# 终端 B：手动模式（脚本不自动审批，等你在 SPA 里点）
.\.venv\Scripts\python.exe -m demo.irrigation_approval --manual
```

打开 `http://127.0.0.1:18080/spa/`：

- **① 监视层**：看流式输出、四阶段状态条、span 瀑布图（默认 4 个关键 span）；
- **② 控制层**：看审批卡片（允许 / 拒绝 / 改成 60 秒）、xterm 终端、接管切换；
- **③ 编排层**：首页问题陈述 +「试试看」按钮，场景卡片执行。

## D. 连续演示与重置

```powershell
# 连续 10 次（证据写到 data/demo_runs/run10_*.log）
1..10 | ForEach-Object {
  .\.venv\Scripts\python.exe -m demo.irrigation_approval *> "data\demo_runs\run10_$_.log"
}

# 两次演示之间重置（<5 秒）：清理进程 + 演示库 + 演示审计
powershell -ExecutionPolicy Bypass -File demo\reset.ps1
```

## E. 拒绝 / 改参分支（答辩追问时用）

```powershell
.\.venv\Scripts\python.exe -m demo.irrigation_approval --decision rejected
.\.venv\Scripts\python.exe -m demo.irrigation_approval --decision modify
```

- 拒绝：工具不执行，Agent 收到 1003，控制台审计显示
  `control_pump blocked / 1003 / 原始 args`；脚本 `branch_ok=True`、exit 0（约 11.1s）。
- 改成 60 秒：审批注入参数经 Guard 重新校验后，实际下发 `duration=60`；
  审计显示 `passed / args.duration=60`（不是原始 300）；脚本 exit 0（约 10.9s）。
- 注意：脚本按**分支应有的结果**判定，不是"退出码 0 就算成功"；
  判定条件见 `docs/evidence/v30_batch_20261107/branch_rejected_and_modify.txt`。

## F. 六分钟答辩技术排练

```powershell
# 依次跑 允许 / 拒绝 / 改成 60 秒（每次前自动 reset），约 35 秒
powershell -ExecutionPolicy Bypass -File demo\rehearse_6min.ps1
```

预期：`TECHNICAL REHEARSAL: 3 / 3 branches passed`。
口播配时见 `docs/答辩6分钟_排练稿.md`；口头演练与录屏为人工项。

## G. 常见问题

| 现象 | 处理 |
|---|---|
| 端口 1884/8021 被占 | `demo\reset.ps1` 后用 `Get-NetTCPConnection -LocalPort 1884,8021` 查残留进程 |
| `ollama serve` 起不来（11434 绑定失败） | 系统排除端口范围占用：`netsh int ipv4 show excludedportrange protocol=tcp` 确认；改用 `OLLAMA_HOST=127.0.0.1:11500` 重启 serve，`OLLAMA_BASE` 同步 |
| `--agent ollama` 报"Ollama 不可达" | 未起服务或 OLLAMA_BASE 端口不对；启动 serve 后重试（预热后再跑演示） |
| `python` 命令无输出/静默失败 | PATH 上是坏 shim，改用 `.venv\Scripts\python.exe` 全路径 |
| 审批卡片不出现 | 确认 Hub 版本为 v3.0（`/healthz` 正常）、浏览器已连 `/ws/events` |
| 终端不可输入 | 控制层默认"Agent 控制"，点右上「接管终端」 |
| 工作流卡住 | 默认审批超时 90s；演示脚本设 45s，超时会返回 1003 并写审计 |

---

*配套：`docs/试错记录.md`、`docs/测试报告_v3.0.md`、`docs/口径速查表.md` §7*
