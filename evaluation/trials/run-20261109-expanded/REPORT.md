# Travelmind 评测报告

- 全部 trial：36；有效：36；invalid：0
- 分母口径：delivered_plan

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 21 / 36 | 58.3% |
| 部分交付率 PDR | 8 / 36 | 22.2% |
| 预期结果匹配率 OMR | 32 / 36 | 88.9% |
| 硬约束通过率 HPR | 29 / 29 | 100.0% |
| 首轮通过率 FPR | 27 / 29 | 93.1% |
| 必去满足率 MSR | 8 / 12 | 66.7% |
| 返工修复率 RRR | 2 / 2 | 100.0% |

- 池外实体率：0 / 180 个引用
- 平均规划修订轮数：0.611；平均快照数：1.611
- 软质量分均值：86.18（n=29）
- 端到端耗时 median/min/max/P95：68.492/6.903/7066.83/183.537s（n=36）
- 结果分布：{'CORRECT_REJECT': 6, 'FAILED': 1, 'PARTIAL': 8, 'SUCCESS': 9, 'SUCCESS_WITH_WARNINGS': 12}
- 评价标签分布：{'MATCH': 32, 'MISMATCH': 3, 'OVER_REJECT': 1}

## 安全（仅 expected_feasible 标签）

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 不可行 trial 数 | - | 6 |
| 正确拒绝率 SRR | 6 / 6 | 100.0% |
| 误接受率 WAR | 0 / 6 | 0.0% |
| 不安全交付率 | 0 / 6 | 0.0% |
| 部分交付率（不可行样本） | 0 / 6 | 0.0% |
| 非硬拒绝交付率 | 0 / 6 | 0.0% |
| 过度拒绝率 ORR | 1 / 30 | 3.3% |
- 不可行 trial 结果分布：{'CORRECT_REJECT': 6}
- 不可行 trial 触发码：{'candidate_pool_preference_conflict': 3, 'missing_must_visit': 1, 'physical_time_deadlock': 2, 'route_structure': 3}

## Fixture Expectations

- 已评估 trial：29
- 违规次数 / 涉及 trial：19 / 8
- 按规则：{'outdoor_on_bad_day_max': 19}

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 12 | 9 | 100.0% | 91.7% | 79.13 | 47.489s | 1960.8 | 852.8 | 2813.6 | 1.0 |
| planner_reviewer | 12 | 10 | 100.0% | 83.3% | 91.1 | 70.15s | 7109.8 | 1296.2 | 8406.0 | 3.08 |
| planner_reviewer_time_check | 12 | 10 | 100.0% | 91.7% | 87.6 | 123.178s | 11526.0 | 2234.2 | 13760.2 | 5.67 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| jingdezhen-3d-sunny-history | 3 | 3 | 100.0% | 100.0% | 89.67 |
| lijiang-3d-allrain-history | 3 | 3 | 100.0% | 100.0% | 73.39 |
| lijiang-5d-sunny-slowpace | 3 | 3 | 100.0% | 100.0% | 95.67 |
| nanjing-3d-singlerain-history | 3 | 3 | 100.0% | 100.0% | 88.67 |
| nanjing-3d-sunny-history | 3 | 3 | 100.0% | 100.0% | 93.67 |
| nanjing-3d-tighthours-negative | 3 | 3 | 100.0% | 100.0% | 93.67 |
| sanya-1d-indooronly-empty-pool-negative | 3 | 0 | N/A | 100.0% | None |
| sanya-3d-allrain-outdoor-negative | 3 | 3 | 100.0% | 100.0% | 62.0 |
| shanghai-1d-sunny-nightlife | 3 | 2 | 100.0% | 0.0% | 89.5 |
| shanghai-1d-twohour-three-must-negative | 3 | 0 | N/A | 100.0% | None |
| shanghai-3d-beyond-forecast | 3 | 3 | 100.0% | 100.0% | 89.67 |
| shanghai-3d-smallpool-negative | 3 | 3 | 100.0% | 66.7% | 87.0 |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| planner | 36 | 50607.274 | 7010155.0 |
| time_check | 12 | 22047.067 | 46632.2 |
| reviewer | 24 | 14388.336 | 56476.3 |
| snapshot_gate | 36 | 1.917 | 13.4 |
| snapshot_reviewer | 24 | 1.544 | 9.5 |
| snapshot_time_check | 12 | 1.256 | 5.1 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。