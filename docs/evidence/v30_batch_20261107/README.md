# v3.0 三层控制台证据包（2026-11-07）

本目录是 v3.0 批次的**过程证据**，与 `docs/测试报告_v3.0.md` 配套。
所有数字均可在本目录文件与仓库代码中复核；SIL/HIL 定义见 `docs/口径速查表.md` §6.3。

## 文件索引

| 文件 | 内容 | 复现命令 |
|---|---|---|
| `pytest_v30.xml` | 全量测试 JUnit 结果（321 项，0 失败/0 错误/0 跳过） | `.\.venv\Scripts\python.exe -m pytest -q --junitxml=docs/evidence/v30_batch_20261107/pytest_v30.xml` |
| `demo_close_loop_events.jsonl` | 一次完整演示的事件流（agent.token / tool.stage / hitl.request / hitl.decision / span / terminal.command / demo.summary） | `.\.venv\Scripts\python.exe -m demo.irrigation_approval` |
| `demo_close_loop_audit.jsonl` | 演示审计记录（含 `tool=hitl.approval` 的审批决策，哈希链 `pre_hash`/`rec_hash`） | 同上；用 `scripts/attestation.py audit-verify` 校验 |
| `summary_10runs.txt` | 连续 10 次演示的退出码、耗时、工作流/审批/设备就绪数字 | 见 `docs/demo_操作手册.md` §D |
| `fallback_and_reset.txt` | 真机离线 → SIL 兜底实测；reset 0.59s | 见 `docs/demo_操作手册.md` §B/§D |
| `branch_rejected_and_modify.txt` | 拒绝 / 改成 60 秒两个分支的实测与成功判定 | 见 `docs/demo_操作手册.md` §E |
| `secrets_check.txt` | 已跟踪密钥扫描、secrets.h 忽略状态、历史检查结论 | 推送前安全自查 |
| `rehearse6_results.txt` | 六分钟答辩技术排练 3/3 | 见 `docs/答辩6分钟_排练稿.md` |
| `coverage_summary.txt` | 行覆盖率总览与关键模块 | pytest-cov 生成 `coverage-v30.json` 后汇总 |

## 关键数字（本次实测）

- 测试 **321 项全部通过**（v2.0 基线 261 + v3.0 批次 60）
- 行覆盖率 **72.1%**（3221 / 4467 statements）
- 演示闭环 **10/10 通过**，端到端 10.8–11.1s；工作流均值 5.26s；审批等待均值 2.99s
- 审批分支：拒绝 **11.1s（exit 0，审计 blocked/1003）**；改成 60 秒 **10.9s（exit 0，审计 duration=60）**
- 六分钟技术排练 **3/3 通过**（允许 11.6s / 拒绝 11.1s / 改 60 秒 11.5s）
- `control_pump` 写回执 **100–141ms（SIL 模拟器）**
- **不是真机数字**：真机命令→回执 152ms / 自动停泵 5.1s 来自
  `docs/evidence/real_device_e2e_20261024.txt`，本次未重测

## 事件流里的三段关键证据

1. `hitl.request`：`summary = "AI 想启动水泵 300 秒，是否允许？"`，
   `options = [允许, 拒绝, 改成 60 秒]`；
2. `tool.stage`：`control_pump` 的 `identified → executing → result` 三阶段，
   审批期间 `tool.stage` 停在 `identified`（证明调用真的被暂停）；
3. `span.start` / `span.end`：`tool.run_workflow`、3 个步骤、`guardrail.approval`
   共 5 个 span 全部闭合（采集收尾 0.3s 后统计）。

## 诚实边界

- 本证据包全部来自 **Windows 11 + Python 3.14.3** 的本地运行；
  CI 的 ubuntu 矩阵另跑一遍同样的 321 项。
- 交互终端在 Windows 是持久管道会话，不是 PTY；证据里的 `mode` 字段会如实写
  `pipe`；POSIX 下为 `pty`。
- `agent.token` 的来源是**确定性 script Agent**（`source=script-agent`），
  不是大模型 token；无 LLM Key 时不会冒充模型输出。
