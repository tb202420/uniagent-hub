# 过程证据索引（docs/evidence/）

> 用途：答辩/研究报告的原始实验数据。每个文件/目录对应 `docs/dev_log.md` 中的哪张表，
> 在此逐一说明；评委追问"这个数据怎么来的"时可现场翻到对应原始输出。

## 一、证据清单

### 阶段 1-3（历史阶段，见 dev_log §二/§五/§六）

| 文件 | 对应 dev_log | 说明 |
|---|---|---|
| `phase2_e2e_results.md` | §5.2 | 阶段 2 端到端实测（6 工具统一注册 / 重启恢复 / REST 真实调用） |
| `phase3_e2e_results.md` | §6.2 | 阶段 3 端到端实测（9 工具 / office_cooling 闭环 / 限流 / CLI 8 脚本） |
| `final_fix_verification.md` | §8 | 最终检查 12 ERR + 3 SUP 的逐项验证记录 |

### 阶段 4 · 演示级交付（见 dev_log §八 与 demo_rehearsal_log.md）

| 文件 | 对应记录 | 说明 |
|---|---|---|
| `demo_start_1.txt` ~ `demo_start_3.txt` | `docs/test-reports/demo_rehearsal_log.md` | 3 次彩排的**一键启动原始输出**（P1-P6 就绪过程 + warmup 4 项检查） |
| `demo_rehearsal_1.txt` ~ `demo_rehearsal_3.txt` | 同上 | 3 次彩排的**五幕执行 + 8 项评分原始输出**（均 8/8） |
| `phase4_offline_verification.md` | dev_log §八 / demo_fallback/README.md | 断网降级可用性取证（进程级 + 回包指纹双重证据） |

### 阶段 4 · 本地 LLM 接入（见 dev_log §九）

| 文件 | 对应 dev_log | 说明 |
|---|---|---|
| `ollama_probe_1.json` | §9.1 | **模型能力探针原始数据**：用 Hub 真实 `tools/list`（9 工具）验证三条通道 —— Q1 原生 `tool_calls` 6/6、Q2 OpenAI 兼容 1/1、Q3 提示词计划 3/3 可解析但多步不可靠 |
| `llm_stability_temp0/` | §9.3 温度实验表 | **温度对比实验（temp=0.0）**，5 次完整原始日志：原生模式 5/5、动作正确 5/5、数值保真 4/5、均值 22.6s。**答辩重点数据**（与 temp=0.3 的 3/5、0/5 形成对照） |
| `llm_stability_final/` | §9.4 | **最终确认批次（temp=0.0 · 演示目标）**，5 次完整原始日志：原生模式 5/5、动作正确 5/5、数值保真 4/5 |
| `llm_stability_final_branch/` | §9.4 | **最终确认批次（temp=0.0 · 条件分支用例）**，3 次完整原始日志：分支判断正确 3/3（不该开空调时确实没开） |
| `llm_stability/SUMMARY.md` | §9.2 #18 + §9.3 | 中间批次**汇总统计**（temp=0.3 · 演示目标：原生 3/5、数值保真 0/5）。逐次原始日志已按精简原则删除，保留了暴露"模板 token 泄漏被当结论打印""模型谎称已执行未执行操作"两类问题的结论性描述 |
| `llm_stability_branch/SUMMARY.md` | §9.2 #19 | 中间批次**汇总统计**（temp=0.3 · 条件分支：分支判断 3/3）。这是串行强制修复有效性的首个证据 |

## 二、精简原则（2026-09-26 归档整理）

- **完整保留**：最终确认批次（`llm_stability_final/` + `llm_stability_final_branch/`）
  与温度对比实验（`llm_stability_temp0/`）的逐次原始日志 —— 这两组是答辩引用数据；
- **只留汇总**：中间批次（`llm_stability/` + `llm_stability_branch/`）保留
  `SUMMARY.md`（配置 + 汇总统计 + 暴露的问题 + 相关记录），逐次原始日志删除。
  删除前已将关键结论（含问题现象描述）写入 SUMMARY，无信息丢失。

## 三、复现方式

```powershell
# 一键启动演示栈（离线模式，含本地 broker + Mock 天气 API）
powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -LogToFile

# 五幕彩排 + 8 项自动评分
python -m scripts.demo_rehearsal --label "复现"

# 本地 LLM 能力探针（需先启动 Hub）
python -m scripts.ollama_tool_probe --hub http://127.0.0.1:8020 --out docs/evidence/ollama_probe_1.json

# LLM 稳定性批量评分（串行执行；Ollama 不可并发）
python -m scripts.llm_stability_check --runs 5 --out docs/evidence/llm_stability_final
python -m scripts.llm_stability_check --runs 3 --expect-no-ac `
    --goal "查询会议室温度；只有当温度超过 35 度时才开空调降温" `
    --out docs/evidence/llm_stability_final_branch
```