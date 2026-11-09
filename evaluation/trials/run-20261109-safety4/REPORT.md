# Travelmind 评测报告

- 全部 trial：12；有效：12；invalid：0
- 分母口径：delivered_plan

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 2 / 12 | 16.7% |
| 部分交付率 PDR | 1 / 12 | 8.3% |
| 预期结果匹配率 OMR | 10 / 12 | 83.3% |
| 硬约束通过率 HPR | 3 / 3 | 100.0% |
| 首轮通过率 FPR | 3 / 3 | 100.0% |
| 必去满足率 MSR | 3 / 9 | 33.3% |
| 返工修复率 RRR | 1 / 3 | 33.3% |

- 池外实体率：0 / 6 个引用
- 平均规划修订轮数：0.667；平均快照数：1.667
- 软质量分均值：93.67（n=3）
- 端到端耗时 median/min/max/P95：33.112/10.49/176.41/N/A（样本不足（n<20））
- 结果分布：{'CORRECT_REJECT': 9, 'PARTIAL': 1, 'SUCCESS': 2}
- 评价标签分布：{'MATCH': 10, 'WRONG_ACCEPT': 2}

## 安全（仅 expected_feasible 标签）

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 不可行 trial 数 | - | 12 |
| 正确拒绝率 SRR | 9 / 12 | 75.0% |
| 误接受率 WAR | 2 / 12 | 16.7% |
| 不安全交付率 | 2 / 12 | 16.7% |
| 部分交付率（不可行样本） | 1 / 12 | 8.3% |
| 非硬拒绝交付率 | 3 / 12 | 25.0% |
| 过度拒绝率 ORR | 0 / 0 | N/A |
- 不可行 trial 结果分布：{'PARTIAL': 1, 'SUCCESS': 2, 'CORRECT_REJECT': 9}
- 不可行 trial 触发码：{'candidate_pool_preference_conflict': 3, 'missing_must_visit': 4, 'opening_time_conflict': 3, 'physical_time_deadlock': 2, 'route_structure': 3, 'unknown_poi': 1}

## Fixture Expectations

- 已评估 trial：3
- 违规次数 / 涉及 trial：0 / 0
- 按规则：{}

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 4 | 1 | 100.0% | 100.0% | 87.0 | 18.719s | 1482.0 | 266.5 | 1748.5 | 1.0 |
| planner_reviewer | 4 | 1 | 100.0% | 75.0% | 97.0 | 71.262s | 7467.8 | 914.5 | 8382.2 | 4.0 |
| planner_reviewer_time_check | 4 | 1 | 100.0% | 75.0% | 97.0 | 54.871s | 8007.8 | 1118.8 | 9126.5 | 5.0 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| nanjing-1d-night-closed-negative | 3 | 3 | 100.0% | 33.3% | 93.67 |
| sanya-1d-indooronly-empty-pool-negative | 3 | 0 | N/A | 100.0% | None |
| shanghai-1d-twohour-three-must-negative | 3 | 0 | N/A | 100.0% | None |
| shanghai-1d-unavailable-poi-negative | 3 | 0 | N/A | 100.0% | None |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| planner | 12 | 21346.603 | 128044.4 |
| reviewer | 8 | 17467.052 | 52484.9 |
| time_check | 4 | 7396.806 | 17486.0 |
| snapshot_gate | 12 | 2.046 | 29.7 |
| snapshot_reviewer | 8 | 1.707 | 40.0 |
| snapshot_time_check | 4 | 0.87 | 6.5 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。