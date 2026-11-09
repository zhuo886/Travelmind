# Travelmind 评测报告

- 全部 trial：6；有效：6；invalid：0
- 分母口径：delivered_plan

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 0 / 6 | 0.0% |
| 部分交付率 PDR | 0 / 6 | 0.0% |
| 预期结果匹配率 OMR | 6 / 6 | 100.0% |
| 硬约束通过率 HPR | 0 / 0 | N/A |
| 首轮通过率 FPR | 0 / 0 | N/A |
| 必去满足率 MSR | 0 / 3 | 0.0% |
| 返工修复率 RRR | 0 / 0 | N/A |

- 池外实体率：0 / 0 个引用
- 平均规划修订轮数：0.0；平均快照数：1.0
- 软质量分均值：None（n=0）
- 端到端耗时 median/min/max/P95：48.781/16.497/68.958/N/A（样本不足（n<20））
- 结果分布：{'CORRECT_REJECT': 6}
- 评价标签分布：{'MATCH': 6}

## 安全（仅 expected_feasible 标签）

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 不可行 trial 数 | - | 6 |
| 正确拒绝率 SRR | 6 / 6 | 100.0% |
| 误接受率 WAR | 0 / 6 | 0.0% |
| 不安全交付率 | 0 / 6 | 0.0% |
| 部分交付率（不可行样本） | 0 / 6 | 0.0% |
| 非硬拒绝交付率 | 0 / 6 | 0.0% |
| 过度拒绝率 ORR | 0 / 0 | N/A |
- 不可行 trial 结果分布：{'CORRECT_REJECT': 6}
- 不可行 trial 触发码：{'candidate_pool_preference_conflict': 3, 'missing_must_visit': 1, 'physical_time_deadlock': 2, 'route_structure': 3}

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 2 | 0 | N/A | 100.0% | None | 25.727s | 1171.5 | 170.5 | 1342.0 | 1.0 |
| planner_reviewer | 2 | 0 | N/A | 100.0% | None | 51.707s | 2298.0 | 389.0 | 2687.0 | 2.0 |
| planner_reviewer_time_check | 2 | 0 | N/A | 100.0% | None | 64.751s | 2786.5 | 489.5 | 3276.0 | 3.0 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| sanya-1d-indooronly-empty-pool-negative | 3 | 0 | N/A | 100.0% | None |
| shanghai-1d-twohour-three-must-negative | 3 | 0 | N/A | 100.0% | None |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| planner | 6 | 26780.754 | 44306.7 |
| reviewer | 4 | 22357.749 | 31062.3 |
| time_check | 2 | 17625.917 | 26348.1 |
| snapshot_time_check | 2 | 1.178 | 2.0 |
| snapshot_gate | 6 | 1.137 | 2.4 |
| snapshot_reviewer | 4 | 0.668 | 1.7 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。