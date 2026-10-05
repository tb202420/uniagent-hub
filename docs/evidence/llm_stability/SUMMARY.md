# 中间批次汇总：temp = 0.3 · 演示目标（已归档）

> 状态：**中间批次**。原始逐次日志已按 `docs/evidence/README.md` 的精简原则删除，
> 汇总统计保留于此；最终数据见 `../llm_stability_final/` 与 `../llm_stability_temp0/`。

## 配置

| 项 | 值 |
|---|---|
| 模型 | `gemma4local:latest`（Gemma 4 26B-A4B IQ3_XXS） |
| 后端 | Ollama 原生 `/api/chat`（`num_ctx=16384`、`repeat_penalty=1.1`、`num_predict=1024`） |
| 温度 | **0.3** |
| 目标 | "会议室太热了，帮我降温到 26 度" |
| 次数 | 5 |
| 执行方式 | 串行（`scripts/llm_stability_check.py --runs 5`） |

## 汇总统计

| 指标 | 结果 |
|---|---|
| 原生 tool_calls 模式成功 | **3/5** |
| 给出结论 | 3/5 |
| 数值转述保真 | **0/5** |
| 正确调用 `ac_control` | 4/5 |
| 出现重复退化 | 0/5 |
| 平均耗时 | 12.3s |

## 该批次暴露的两个问题（已在正式版本修复）

1. **模板控制 token 泄漏且被当作有效结论打印**
   结论输出为 `<tool_call|><|tool_response>`，属 Gemma 模板渲染残留。
   → 修复：`_clean_answer()` 扩展 token 白名单，并在剥离后无实质内容时返回空串，
   由调用方触发降级（不再把垃圾当结论打印）。

2. **模型谎称已执行未执行的操作（言行不一）**
   实测：只调用了 `get_temperature`（返回 31.5），却输出
   "会议室当前温度是 29 度。由于超过了 28 度，已为您开启空调并调至 26 度。"
   ——温度数值编造（31.5→29）、动作编造（未调用 `ac_control`）。
   → 修复：见温度实验（`../llm_stability_temp0/`）——温度降到 0.0 后数值保真提升至 4/5。

## 相关记录

- dev_log §九 9.2（工程问题 #18）与 9.3（温度实验）
- 对照批次：`../llm_stability_temp0/`（temp=0.0，数值保真 4/5）