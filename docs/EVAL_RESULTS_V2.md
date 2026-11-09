# Travelmind 评测结果 v2（2026-11-06）

> 口径见 [EVAL_SPEC_V2.md](./EVAL_SPEC_V2.md)。原始记录：
> `evaluation/trials/run-20261107-v2/`（9 条有效 trial + `infra/` 下 2 条 429 审计记录）。
> 本轮只跑 3 个 must_visit 案例 × A/B/C × k=1，用于验证注入链路，不替代 v1 的 30 条主消融。

## 0. 运行概况

| 项 | 值 |
|---|---|
| 案例 | nanjing-3d-sunny-history、shanghai-1d-sunny-nightlife、lijiang-5d-sunny-slowpace |
| 模式 | A `planner_only` / B `planner_reviewer` / C `planner_reviewer_time_check` |
| trial | **9**（3 × 3 × 1） |
| invalid | **0** |
| 模型 | glm-4.5-flash（temperature=0） |
| 限流 | 上海 B/C 首轮各触发一次账户级 429，记录移入 `infra/`；冷却后串行重跑成功（314.5s / 203.9s） |

## 1. 总体指标

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 7 / 9 | 77.8% |
| 部分交付率 PDR | 1 / 9 | 11.1% |
| 预期结果匹配率 OMR | 7 / 9 | 77.8% |
| 硬约束通过率 HPR | 8 / 9 | 88.9% |
| 首轮通过率 FPR | 6 / 9 | 66.7% |
| **用户点名必去命中率 MSR** | **9 / 9** | **100.0%** |
| 返工修复率 RRR | 2 / 2 | 100.0% |
| 池外实体率 OOR | 1 / 55 个引用 | 1.8% |
| 软质量分均值 | 9 次 | 92.11 / 100 |

- 端到端耗时：median **205.8s**，min 99.6s，max 314.5s（n=9，P95 样本不足）。
- 结果分布：`SUCCESS_WITH_WARNINGS` 6、`SUCCESS` 1、`PARTIAL` 1、`HARD_FAIL` 1。
- 评价标签：`MATCH` 7、`MISMATCH` 1、`HARD_FAIL` 1。

## 2. A/B/C 对照（各 3 次）

| 指标 | A 单轮 Planner | B + Reviewer | C + Time Check |
|---|---|---|---|
| 硬约束通过率 HPR | 66.7% | **100%** | **100%** |
| 预期匹配率 OMR | 33.3% | **100%** | **100%** |
| 软质量均分 | 83.67 | **98.0** | 94.67 |
| 中位耗时 | 99.6s | 249.6s | 222.6s |
| 平均输入 Token | 2,228 | 11,728 | 7,172 |
| 平均 LLM 调用 | 1.0 | 4.67 | 3.67 |
| 用户点名必去命中 | 3/3 | 3/3 | 3/3 |

## 3. must_visit 注入验证（v2 的核心）

| 案例 | 点名景点 | A | B | C |
|---|---|---|---|---|
| nanjing-3d-sunny-history | 玄武湖景区 | 命中 | 命中 | 命中 |
| shanghai-1d-sunny-nightlife | 上海海洋水族馆 | 命中 | 命中 | 命中 |
| lijiang-5d-sunny-slowpace | 束河古镇 | 命中 | 命中 | 命中 |

- 9 条 trial 的 `must_visit_expected` 均非空，`must_visit_ok` 均为 `true`；
- 说明 `一定要去“…”` 已被 `extract_explicit_place_requests()` 抽取，并经 `active_must_visit()` 进入生产约束；
- 与 v1 的差别：v1 的 A 组曾漏排玄武湖但仍 `hard_pass=true`（`must_visit` 只是元数据）；v2 的 A 组在 query 注入后主动安排了点名景点。**因此 v2 的 MSR 100% 不能全部归功于 Reviewer**，它同时反映了"把用户点名写进 query"对 Planner 行为的影响。

## 4. 本轮失败样本

| 案例 | 模式 | 结果 | 原因 |
|---|---|---|---|
| shanghai-1d-sunny-nightlife | A | `HARD_FAIL`（unknown_poi） | 路线包含候选池外的「外滩」，同时正确包含「上海海洋水族馆」；池外实体 1/55 |
| lijiang-5d-sunny-slowpace | A | `PARTIAL`（MISMATCH） | `habit_constraint`：Day2 景点数量偏多；allowed 只含 SUCCESS 家族，标签与实际降级不一致 |

说明：Lijiang A 的 PARTIAL 是"慢节奏偏好被判定为超量"，不是 must_visit 失败；B/C 通过审核与时间复核后回到 SUCCESS 家族。

## 5. 诚实边界

1. 本轮 n=9，只用于验证 must_visit 注入与天气规则，**不能替代 v1 的 30 条主消融**；
2. MSR 9/9 只代表 3 个案例、k=1；不宣称"所有点名需求都能满足"；
3. RRR 2/2 样本极小；
4. OOR 1/55（1.8%）来自 A 组的单次幻觉，不能写"彻底解决幻觉"；
5. v2 没有重跑三亚全雨负样本；天气新规则的效果需在后续负样本回归中单独验证；
6. 上海 B/C 首轮 429 已作为 `infra/` 审计保留，未计入有效质量数据。

## 6. 可写句式

- 将用户点名景点写入 query 后，3 个案例 × 3 模式的 9 次运行中，点名必去命中率 **9/9（100%）**，`missing_must_visit` 已进入 L0 硬约束。
- 在 9 次 v2 运行中，Reviewer 把 A 组的硬约束通过率 **66.7% → 100%**、预期匹配率 **33.3% → 100%**，代价是输入 Token ×5.3、中位耗时 ×2.5。

## 7. E2 Checkpoint 增量修改配对实验（27 组）

脚本：`tests/eval/checkpoint_benchmark.py`；数据：`evaluation/checkpoint_benchmark/`。

**设计**：15 个 checkpoint（来自本轮 6 条负样本 trial + 9 条 v2 trial，按案例×类型去重）→ 27 组修改探针。A 与 B 使用同一 fixture、同一指令、同一候选池与天气；唯一差别是 B 复用历史路线（`restore_modification_state`）。执行模式 `planner_only`，`max_review_rounds=1`，不含 `route_distance_check`、餐食与贴士。

| 指标 | A 全量重规划 | B Checkpoint | 变化 |
|---|---|---|---|
| 重规划 P50 (ms) | 69,119 | 61,048 | **-11.7%** |
| 输入 Token 合计 | 62,904 | 67,052 | **+6.6%** |
| 修改指令满足率 | 100% | 100% | 持平 |
| 未修改内容保留率 | 73.5% | **90.6%** | **+17.1pp** |
| 修改后硬约束通过率 | 81.5% | **92.6%** | **+11.1pp** |

**稳健性复核**：pair 24 / 26 的 A 臂各发生一次 `OpenAIAPIError` 重试，输入 Token 与耗时被放大。剔除这 2 组后（n=25）：

| 指标 | A | B | 变化 |
|---|---|---|---|
| 重规划 P50 (ms) | 64,019 | 63,789 | **-0.4%（不显著）** |
| 输入 Token 合计 | 53,522 | 62,167 | +16.2% |
| 硬约束通过率 | 22/25 | 24/25 | +8pp |

**结论（必须按这个口径写）**：

1. 在"冻结候选池 + 只跑 planner"的配对实验中，checkpoint 复用**没有稳定降低 P50**（含重试 -11.7%，剔除后 -0.4%）；
2. 输入 Token **没有下降，反而 +6.6%~+16.2%**，因为历史路线被写进 prompt；
3. checkpoint 的真实收益是**保留率（+17.1pp）与硬约束通过率（+11.1pp）**，即"改得更准、更少误伤其他安排"；
4. 不能写"-31.8% / -15.2%"；这两个数字在本仓库不可复现，原项目也已撤销。

可写句式（保守版）：

> 基于应用层 checkpoint 复用历史路线与候选状态，27 组配对修改探针中，未修改内容保留率 73.5% → 90.6%、修改后硬约束通过率 81.5% → 92.6%；Planner 重规划 P50 无稳定改善（放宽重试后 -0.4%），输入 Token +6.6%。
