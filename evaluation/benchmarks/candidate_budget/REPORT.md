# 有界 ReAct 检索：预算合规与幻觉阻断

> 数据：已冻结 trial 的落盘字段，纯聚合，0 次调用
> 样本：81 条（有效 81 条）

## 1. 预算合规

- 上限：`effective_api_budget ≤ 10`、`candidate_max_rounds ≤ 2`
- trial 口径：**N/A**
- 原因：已冻结 trial 的 candidate_api_calls 全为 0（harness 从 planner 起跑，不经过检索节点），预算合规无法由这批数据证明；预算行为改由 gap_fill 的 bounded_react 臂覆盖
- 受控场景口径：**28 / 28（100.0%）**，最大 2 次（上限 10）
- 来源：`evaluation\benchmarks\gap_fill\summary.json`；受控场景跑的是真实决策队列与执行器（仅检索结果被桩替换）

| 模式 | trial | 中位检索次数 | 最大 |
|---|---:|---:|---:|
| planner_only | 27 | 0 | 0 |
| planner_reviewer | 27 | 0 | 0 |
| planner_reviewer_time_check | 27 | 0 | 0 |

## 2. 幻觉阻断（三段证据）

| 层级 | 指标 | 值 |
|---|---|---:|
| 引用级 | 池外景点引用 / 总引用 | 3 / 505（0.6%） |
| trial 级 | 首版含 `unknown_poi` 的 trial | 9 |
| 拦截级 | 首版有、交付已修掉的 trial | **6** |

| 模式 | trial | `unknown_poi` L0 |
|---|---:|---:|
| planner_only | 27 | 3 |
| planner_reviewer | 27 | 0 |
| planner_reviewer_time_check | 27 | 0 |

## 3. 点名必去覆盖

- 全量：39 条参与，通过 33 条（84.6%）

| 数据桶 | 参与 | 通过 | 覆盖率 | 未通过 trial |
|---|---:|---:|---:|---|
| v1 | 30 | 24 | 80.0% | nanjing-3d-sunny-history::planner_only、nanjing-3d-sunny-history::planner_reviewer、nanjing-3d-sunny-history::planner_only… |
| v2 | 9 | 9 | 100.0% | — |

### v3 安全样本（单列，不进可行集分母）

- trial：6；结果分布：{'CORRECT_REJECT': 6}
- `must_visit` 参与 3 条，通过 0 条
- 安全样本 intended 为不可行；must_visit_ok=False 与 CORRECT_REJECT 一致，不算失败

## 4. 去重与缓存

- 可复核：**False**
- 现有 trial 未落盘 candidate_search_trace；该字段自本轮起在 run_trials 中补写，去重与缓存命中需下一轮运行才有数据

## 5. 读法

- “从源头阻断幻觉”的可复核表述是：池外引用率 + 首版 unknown_poi 被 Reviewer 修掉的数量，不能只写池外引用率。
- 预算合规率 100% 只说明没超上限，不说明检索是否高效。
- 去重与缓存命中本轮为 N/A，不得用 0 代替。