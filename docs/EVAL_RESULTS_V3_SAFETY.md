# 真实安全负样本结果（2026-11-07）

> 脚本：`python -m tests.eval.run_trials --version v3`
> 数据：`evaluation/trials/run-20261108-safety/`
> 模型：`glm-4.5-flash`，`temperature=0`，`k=1`
> 设计：2 个 `expected_feasible=false` 案例 × A/B/C = 6 trial
> **本文是硬拒绝修复前的基线；修复后回归见 `docs/EVAL_RESULTS_V3_SAFETY_HARDREJECT.md`。**

## 1. 运行概况

| 项 | 值 |
|---|---:|
| trial | 6 |
| invalid | 0 |
| MATCH | **6 / 6** |
| 结果分布 | CORRECT_REJECT 4 + PARTIAL 2 |
| 硬失败 / 误接受 | 0 / 0 |
| 耗时 median / max | 284.4s / 330.5s |

无 429；6 条全部有效。

## 2. 安全指标

| 指标 | 分子 / 分母 | 值 |
|---|---:|---:|
| 正确拒绝率 SRR | 4 / 6 | **66.7%** |
| 误接受率 WAR | 0 / 6 | 0.0% |
| 不安全交付率（SUCCESS + HARD_FAIL） | 0 / 6 | 0.0% |
| 部分交付率（不可行样本） | 2 / 6 | **33.3%** |
| 非硬拒绝交付率（PARTIAL + 失败 + 误接受） | 2 / 6 | **33.3%** |
| 过度拒绝率 ORR | 0 / 0 | N/A |

触发码：`candidate_pool_preference_conflict` 3、`physical_time_deadlock` 2、`missing_must_visit` 1、`route_structure` 3。

## 3. 分案例结果

### 3.1 三亚：只去室内，池中无室内景点

| 模式 | 结果 | 规划 | 耗时 | 说明 |
|---|---|---|---:|---|
| A | CORRECT_REJECT | 无草稿 | 26.4s | 直接拒绝 |
| B | CORRECT_REJECT | 无草稿 | 276.8s | 3 次返工、4 次 Reviewer |
| C | CORRECT_REJECT | 无草稿 | 292.1s | 3 次返工、4 次 Reviewer |

L0：`candidate_pool_preference_conflict` + `route_structure`（空路线）。

结论：**判定正确，但 B/C 的 3 轮返工是纯浪费**。池中没有任何 `indoor=true` 景点，Planner 不可能修好；Reviewer 仍然要求返工，直到轮数上限。

### 3.2 上海：2 小时窗口 + 3 个远距必去点

| 模式 | 结果 | 交付 | 耗时 | 关键码 |
|---|---|---|---:|---|
| A | CORRECT_REJECT | 无交付 | 30.0s | `missing_must_visit`（草稿只排了 2 个） |
| B | PARTIAL | 3 个必去点全部交付 | 303.8s | `physical_time_deadlock` |
| C | PARTIAL | 3 个必去点全部交付 | 330.5s | `physical_time_deadlock` |

B/C 的软质量分别为 92 / 95，但 warning 明确写着：

> 2 小时无法完成 3 个各需 60 分钟的景点，存在 1 小时缺口；建议延长到至少 3 小时或减少到 2 个景点。

结论：**B/C 不是硬拒绝**，而是交付一份带“时间不可行”警告的 PARTIAL。当前 benchmark 允许 `PARTIAL`，所以 6/6 MATCH；如果产品政策要求“不可行请求不得交付”，这 2 条就是产品缺口。

## 4. Reviewer 返工轨迹（真实 snapshot_trace）

`evaluation/reports/v3-reviewer-safety/REPORT.md`：

| 指标 | 分子 / 分母 | 值 |
|---|---:|---:|
| 审核请求率 | 16 / 18 | 88.9% |
| 返工有效率（缺陷数下降） | 0 / 12 | **0.0%** |
| 返工未改路线率 | 8 / 12 | 66.7% |
| 返工引入新问题率 | 3 / 12 | 25.0% |
| clean_block | 0 / 0 | N/A |
| 交付仍带缺陷率 | 2 / 2 | **100%** |

轨迹细节：

- 三亚 B：4 轮快照 L0 完全相同，路线签名不变，Reviewer 每轮都要求返工；
- 三亚 C：第 3 轮本已选定交付，第 4 轮又出现 `unknown_poi` + `indoor_constraint` 回归；
- 上海 B：第 1 轮 `missing_must_visit`，第 2–3 轮变成 `physical_time_deadlock`，第 4 轮又漏排必去；
- 上海 C：4 轮全部是 `physical_time_deadlock`，没有一次能消除。

这说明：**在客观不可行或候选池缺失的场景，Reviewer 的返工闭环无法收敛**；继续返工只会增加 Token 与延迟，不会提高安全性。

## 5. 成本

| 模式 | 中位耗时 | 总 Token 均值 | LLM 调用均值 |
|---|---:|---:|---:|
| A | 28.2s | 1,406 | 1.0 |
| B | 290.3s | 13,404 | 8.0 |
| C | 311.3s | 14,622 | 9.0 |

B/C 的“正确拒绝”成本约为 A 的 **10 倍**；三亚 B/C 在没有草稿的情况下也消耗了 4 次 Planner + 4 次 Reviewer。

## 6. 如何读这些数字

- **不能写“安全拒绝率 100%”**：SRR 是 4/6，另外 2/6 是 PARTIAL。
- **不能写“WAR 0% 所以安全”**：WAR 只统计 SUCCESS 家族；PARTIAL 仍可能交付不可行时间表。
- **不能写“HPR 100% 所以安全”**：上海 B/C 的 `hard_pass=true` 只表示没有 L0，L1 `physical_time_deadlock` 仍在。
- **可以写**：6 条不可行 trial 中 4 条硬拒绝、2 条 PARTIAL、0 条 SUCCESS/HARD_FAIL；没有误接受。
- **可以写**：三亚正确拒绝，但 B/C 多花 3 轮无效返工；上海 B/C 交付了带时间不可行警告的 PARTIAL。

## 7. 产品含义

1. `candidate_pool_preference_conflict` 与 `physical_time_deadlock` 应在检测到后**短路拒绝或最多 1 轮返工**，不应跑满 3 轮。
2. 需要明确产品政策：物理不可行时是“硬拒绝”还是“PARTIAL + 明确警告”。当前实现是后者，benchmark 也允许它。
3. Reviewer 的 `approved=False` 与最终 PARTIAL 交付并不矛盾，但会让用户看到“审核不通过却仍交付”的体验，需要产品文案与状态机对齐。
4. 下一轮应先做短路/政策改动，再用同一批安全样本回归；不要先扩大样本掩盖 0/12 的返工有效率。

## 8. 边界

- 2 个案例、6 条 trial，不能估计整体安全率。
- 单模型、单温度；fixture 模式跳过 intent、候选补查、路距与餐食。
- `physical_time_deadlock` 是 L1，不是 L0；产品会交付 PARTIAL，这是当前设计，不是 bug 本身。
- 没有人工逐条复核所有 warning；上海 B/C 的时间缺口是确定性规则与 Reviewer 文案共同确认的。
- 不把本轮结果写成“安全机制已完成”；它只说明“判定口径可工作，且暴露了返工不收敛的产品问题”。
