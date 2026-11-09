# 硬拒绝修复后安全回归（2026-11-07）

> 政策：`physical_time_deadlock` 与 `candidate_pool_preference_conflict` 一律硬拒绝，不再交付 PARTIAL。
> 数据：`evaluation/trials/run-20261107-safety-hardreject-v2/`
> 对照（修复前）：`evaluation/trials/run-20261108-safety/`、`docs/EVAL_RESULTS_V3_SAFETY.md`

## 1. 结论

6 条不可行 trial 全部 `CORRECT_REJECT`：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| CORRECT_REJECT | 4 / 6 | **6 / 6** |
| PARTIAL | 2 / 6 | **0 / 6** |
| SRR | 66.7% | **100%** |
| WAR | 0 / 6 | 0 / 6 |
| 不安全交付 | 0 / 6 | 0 / 6 |
| 非硬拒绝交付 | 2 / 6 | **0 / 6** |
| 中位耗时 | 284.4s | **63.1s** |
| 快照数 | 18 | **8** |

注意：SRR 100% 只针对这 2 个已知不可行案例 × 3 模式，不是整体安全率。

## 2. 分案例

### 三亚：只去室内，池中无室内景点

| 模式 | 结果 | 耗时 | 返工 | Reviewer |
|---|---|---|---:|---:|
| A | CORRECT_REJECT | 29.0s | 0 | 0 |
| B | CORRECT_REJECT | 58.9s | 0 | 1 |
| C | CORRECT_REJECT | 67.2s | 0 | 1 |

修复前 B/C 为 276.8s / 292.1s、各 3 轮返工；现在首轮 Reviewer 后直接 finalize。

### 上海：2 小时窗口 + 3 个远距必去点

| 模式 | 结果 | 耗时 | 返工 | 关键码 |
|---|---|---|---:|---:|---|
| A | CORRECT_REJECT | 31.7s | 0 | `physical_time_deadlock` |
| B | CORRECT_REJECT | 161.1s | 1 | `missing_must_visit`（无进展熔断） |
| C | CORRECT_REJECT | 203.6s | 1 | `physical_time_deadlock` |

修复前 B/C 为 303.8s / 330.5s 且交付 PARTIAL；现在不再交付。

## 3. 成本变化

| 模式 | 修复前中位耗时 | 修复后中位耗时 | 修复前总 Token | 修复后总 Token |
|---|---:|---:|---:|---:|
| A | 28.2s | 30.3s | 1,406 | 1,347 |
| B | 290.3s | **110.0s** | 13,404 | **4,592** |
| C | 311.3s | **135.4s** | 14,622 | **5,200** |

B/C 的 Token 降幅约 65%；这是“停止无效返工”的收益，不是模型变快。

## 4. Reviewer 轨迹

`evaluation/reports/v3-reviewer-safety-hardreject-v2/REPORT.md`：

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| 快照数 | 18 | **8** |
| 审核请求 | 16 / 18 | 6 / 8 |
| 返工事件 | 12 | **2** |
| 返工有效率 | 0 / 12 | 0 / 2 |
| 返工未改路线 | 8 / 12 | 1 / 2 |
| 返工引入新问题 | 3 / 12 | 1 / 2 |
| 交付仍带缺陷 | 2 / 2 | 0 / 0（N/A） |

修复后仍存在 1 次“路线不变且缺陷不变”的返工事件，来自上海 B；它没有继续扩散，因为无进展熔断在下一轮前终止。

## 5. 代码改动

| 文件 | 改动 |
|---|---|
| `app/planning/quality.py` | 新增 `TERMINAL_INFEASIBLE_L0_CODES`、`NON_DELIVERABLE_L1_CODES`、`terminal_infeasibility()`；`choose_snapshot()` 对 `physical_time_deadlock` 返回 FAILED，并优先选择无物理死锁的可交付快照 |
| `app/planning/nodes.py` | `route_after_review` / `route_after_time_check` 检测 terminal infeasibility → `finalize`；新增 `_snapshot_no_progress()`，连续两轮路线与缺陷码相同则停止返工；finalize 失败原因补上 L1 文案 |
| `tests/test_route_quality_rework.py` | 新增物理死锁硬拒绝、可交付 L1 优先、两条短路、无进展熔断测试 |

全量测试 **134 passed**。

## 6. 仍未解决的问题

- 上海 B 最终拒绝码是 `missing_must_visit`，不是 `physical_time_deadlock`：Planner 连续两轮漏排一个必去点，无进展熔断后直接拒绝。判定仍是正确拒绝，但用户看不到“时间不可行”的原因。
- `missing_must_visit` 本身仍是可返工项；如果 Planner 只是偶发漏排，无进展熔断可能在真实可修复场景提前停止。需要更大样本验证。
- 本轮只有 2 个案例 × 3 模式，不能估计整体安全率或误拒绝率。
- 没有改 benchmark 的 `allowed_outcomes`；当前实跑 `partial=0`。如果未来回退到 PARTIAL，`safety.partial_delivery_rate` 会直接暴露，不需要改标签。

## 7. 复现

```powershell
..\.venv\Scripts\python.exe -m pytest -q tests
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 --case shanghai-1d-twohour-three-must-negative --case sanya-1d-indooronly-empty-pool-negative --allow-external-calls --out evaluation/trials/run-20261107-safety-hardreject-v2
..\.venv\Scripts\python.exe -m tests.eval.aggregate_trials --dirs evaluation/trials/run-20261107-safety-hardreject-v2 --out evaluation/trials/run-20261107-safety-hardreject-v2
..\.venv\Scripts\python.exe -m tests.eval.reviewer_reliability --dirs evaluation/trials/run-20261107-safety-hardreject-v2 --out evaluation/reports/v3-reviewer-safety-hardreject-v2
```

## 8. 边界

- 不写“安全率 100%”：只有 2 个已知不可行案例。
- 不写“B/C 成本下降 65%”作为普遍结论：这是不可行场景停止返工的局部收益。
- 不把上海 B 的 `missing_must_visit` 硬拒绝解释成物理时间规则；它是无进展熔断 + L0 拒绝。
- 生产行为已改变：`physical_time_deadlock` 不再交付 PARTIAL。任何引用旧 PARTIAL 结果的文档必须标注“修复前”。