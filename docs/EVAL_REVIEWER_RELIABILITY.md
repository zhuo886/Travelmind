# Reviewer 可靠性基线（零成本 proxy）

> 数据：`evaluation/trials/run-20261106/{s1,s2,s3}`、`run-20261107-v2`、`run-20261107-negative` 共 81 条 trial。
> 脚本：`python -m tests.eval.reviewer_reliability --dirs ... --out evaluation/reports/v3-reviewer`
> 原始报告：`evaluation/reports/v3-reviewer/REPORT.md`、`summary.json`
> 说明：本文件是**零成本离线基线**，不包含任何真实 Reviewer 调用。

## 1. 一句话结论

现有 81 条旧记录只能做 proxy 口径：`6/6` 条“首版 L0 非空且实际返工”的 trial 最终修复了 L0；没有出现“返工后 L0 仍在”的样本；`12/78` 条交付仍带 L1 缺陷；`4/81` 条为 `WRONG_ACCEPT`。这不能回答“Reviewer 是否误打回”和“Planner 是否忽略审核”，需要 v3 的 `snapshot_trace` 与受控挑战集。

## 2. proxy 结果

| 指标 | 分子 / 分母 | 值 | 说明 |
|---|---:|---:|---|
| 有返工尝试 | - | 24 | `planning_revision_rounds >= 1` |
| 首版 L0 且实际返工 | - | 6 | proxy 的返工分母 |
| 返工修复 L0 | 6 / 6 | 100.0% | 首版 L0 非空、最终 L0 空 |
| 返工后 L0 仍在 | 0 / 6 | 0.0% | 不等于“忽略审核”，只是问题仍在 |
| 交付仍带 L1 缺陷 | 12 / 78 | 15.4% | `PARTIAL` 或 `SUCCESS_WITH_WARNINGS` |
| 误接受 WRONG_ACCEPT | 4 / 81 | 4.9% | allowed 为拒绝/部分，实际 SUCCESS |
| 过度拒绝 OVER_REJECT | 0 / 81 | 0.0% | allowed 为成功，实际无交付 |

## 3. 为什么没有 clean_block / regression

现有 81 条 trial 的 `trial_*.json` 只保存：

- `first_draft_l0` / `first_draft_l1`（v2 起有 l1）
- 最终 `l0_codes` / `l1_codes`
- `planning_revision_rounds`
- 部分 run 有 `route_by_day`，但没有每轮快照、审核 approve/reject、返工指令与路线签名。

因此：

- 无法判断“审核打回的草稿是否真的零缺陷” → `clean_block` 必须是 `N/A`；
- 无法判断“返工是否引入新问题” → `regression` 必须是 `N/A`；
- 无法判断“Planner 是否改了路线” → 只能报“最终问题仍在”，不能报“忽略审核”。

v3 起 `run_trials` 会写入 `snapshot_trace`（每轮 l0/l1、soft_score、reviewer_approved、rework_requested、route_signature、is_delivered），这三个指标才能计算。

## 4. 受控挑战集（框架已就绪）

`tests/eval/challenges_v3/` 提供 6 个冻结挑战：

| 挑战 | 注入缺陷 | 预期 |
|---|---|---|
| clean control | 无 | approve |
| unknown_poi | 池外景点 | reject |
| missing_must_visit | 漏排点名景点 | reject |
| weather_outdoor | 全程雨 + 全室外 | reject |
| duplicate_poi | 同日重复景点 | reject |
| overpacked | 单日超过上限 | reject |

本轮只验证框架：stub reviewer 下 5/5 缺陷检出、1/1 正常对照不误打回、关键词 5/5 命中。**这不是真实 Reviewer 能力**；真实结果需下一轮 `--allow-external-calls`。

## 5. 边界（写结论前必读）

- `6/6 修复` 是 proxy 分母下的小样本，不是整体审核收益；24 次返工里只有 6 次首版 L0 且实际返工。
- `4/81 WRONG_ACCEPT` 与 `0/81 OVER_REJECT` 是旧口径 `plan_generated=草稿存在` 的结果；v3 的 `delivered_plan` 语义可能改变分母，不能直接横比。
- 不写“Reviewer 误打回率 0%”——本轮没有测到 clean_block。
- 不写“Planner 忽略审核率”——proxy 只能看到“问题仍在”。
- 不把 stub 挑战结果写进简历或结论。

## 6. 下一轮

```powershell
# 真实 Reviewer 挑战（6 × k=2）
..\.venv\Scripts\python.exe -m tests.eval.reviewer_challenge --allow-external-calls --k 2 --out evaluation/reviewer_challenge/run-20261108

# v3 安全负样本（2 案例 × 3 模式）
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 --case shanghai-1d-twohour-three-must-negative --case sanya-1d-indooronly-empty-pool-negative --allow-external-calls --out evaluation/trials/run-20261108-safety

# 用新 run 重算可靠性（应出现 snapshot_trace 口径）
..\.venv\Scripts\python.exe -m tests.eval.reviewer_reliability --dirs evaluation/trials/run-20261108-safety --out evaluation/reports/v3-reviewer-new
```