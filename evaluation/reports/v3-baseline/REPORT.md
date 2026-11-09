# Travelmind 评测报告

- 全部 trial：81；有效：81；invalid：0
- 分母口径：plan_generated

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 66 / 81 | 81.5% |
| 部分交付率 PDR | 12 / 81 | 14.8% |
| 预期结果匹配率 OMR | 46 / 81 | 56.8% |
| 硬约束通过率 HPR | 78 / 81 | 96.3% |
| 首轮通过率 FPR | 72 / 81 | 88.9% |
| 必去满足率 MSR | 33 / 39 | 84.6% |
| 返工修复率 RRR | 6 / 6 | 100.0% |

- 池外实体率：3 / 505 个引用
- 平均规划修订轮数：0.506；平均快照数：1.506
- 软质量分均值：83.66（n=81）
- 端到端耗时 median/min/max/P95：205.585/35.4/600.287/476.449s（n=81）
- 结果分布：{'HARD_FAIL': 3, 'PARTIAL': 12, 'SUCCESS': 12, 'SUCCESS_WITH_WARNINGS': 54}
- 评价标签分布：{'HARD_FAIL': 3, 'MATCH': 46, 'MISMATCH': 28, 'WRONG_ACCEPT': 4}

## Pass@K（按 case × mode）

| case__mode | k | match | pass@k | pass^k | HPR pass@k |
|---|---|---|---|---|---|
| lijiang-5d-sunny-slowpace__planner_only | 2 | 0 | False | False | True |
| lijiang-5d-sunny-slowpace__planner_reviewer | 2 | 2 | True | True | True |
| lijiang-5d-sunny-slowpace__planner_reviewer_time_check | 2 | 2 | True | True | True |
| nanjing-3d-sunny-history__planner_only | 6 | 4 | True | False | True |
| nanjing-3d-sunny-history__planner_reviewer | 6 | 6 | True | True | True |
| nanjing-3d-sunny-history__planner_reviewer_time_check | 6 | 6 | True | True | True |
| nanjing-3d-tighthours-negative__planner_only | 3 | 0 | False | False | True |
| nanjing-3d-tighthours-negative__planner_reviewer | 3 | 0 | False | False | True |
| nanjing-3d-tighthours-negative__planner_reviewer_time_check | 3 | 0 | False | False | True |
| sanya-3d-allrain-outdoor-negative__planner_only | 6 | 2 | True | False | True |
| sanya-3d-allrain-outdoor-negative__planner_reviewer | 6 | 0 | False | False | True |
| sanya-3d-allrain-outdoor-negative__planner_reviewer_time_check | 6 | 0 | False | False | True |
| shanghai-1d-sunny-nightlife__planner_only | 5 | 1 | True | False | True |
| shanghai-1d-sunny-nightlife__planner_reviewer | 5 | 5 | True | True | True |
| shanghai-1d-sunny-nightlife__planner_reviewer_time_check | 5 | 5 | True | True | True |

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 27 | 27 | 88.9% | 37.0% | 77.52 | 72.863s | 2387.3 | 1190.7 | 3578.1 | 1.15 |
| planner_reviewer | 27 | 27 | 100.0% | 66.7% | 85.81 | 249.565s | 9639.4 | 2493.8 | 12133.3 | 3.93 |
| planner_reviewer_time_check | 27 | 27 | 100.0% | 66.7% | 87.65 | 255.022s | 9073.6 | 2715.1 | 11788.7 | 4.52 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| nanjing-3d-sunny-history | 18 | 18 | 100.0% | 88.9% | 92.33 |
| nanjing-3d-tighthours-negative | 9 | 9 | 100.0% | 0.0% | 92.44 |
| sanya-3d-allrain-outdoor-negative | 18 | 18 | 94.4% | 11.1% | 64.36 |
| jingdezhen-3d-sunny-history | 3 | 3 | 100.0% | 100.0% | 94.67 |
| lijiang-3d-allrain-history | 3 | 3 | 100.0% | 100.0% | 63.95 |
| lijiang-5d-sunny-slowpace | 6 | 6 | 100.0% | 66.7% | 92.33 |
| nanjing-3d-singlerain-history | 3 | 3 | 100.0% | 66.7% | 81.17 |
| shanghai-1d-sunny-nightlife | 15 | 15 | 86.7% | 73.3% | 90.67 |
| shanghai-3d-beyond-forecast | 3 | 3 | 100.0% | 66.7% | 84.0 |
| shanghai-3d-smallpool-negative | 3 | 3 | 100.0% | 100.0% | 79.67 |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| planner | 81 | 94064.247 | 321544.3 |
| reviewer | 54 | 91567.428 | 303865.5 |
| time_check | 27 | 61565.839 | 267439.7 |
| snapshot_reviewer | 54 | 3.3 | 24.9 |
| snapshot_gate | 81 | 2.903 | 19.7 |
| snapshot_time_check | 27 | 1.591 | 6.2 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。