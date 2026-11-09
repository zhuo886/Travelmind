# Travelmind 评测报告

- 全部 trial：6；有效：6；invalid：0
- 分母口径：delivered_plan

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 0 / 6 | 0.0% |
| 部分交付率 PDR | 2 / 6 | 33.3% |
| 预期结果匹配率 OMR | 6 / 6 | 100.0% |
| 硬约束通过率 HPR | 2 / 2 | 100.0% |
| 首轮通过率 FPR | 1 / 2 | 50.0% |
| 必去满足率 MSR | 2 / 3 | 66.7% |
| 返工修复率 RRR | 1 / 3 | 33.3% |

- 池外实体率：0 / 6 个引用
- 平均规划修订轮数：2.0；平均快照数：3.0
- 软质量分均值：93.5（n=2）
- 端到端耗时 median/min/max/P95：284.427/26.428/330.471/N/A（样本不足（n<20））
- 结果分布：{'CORRECT_REJECT': 4, 'PARTIAL': 2}
- 评价标签分布：{'MATCH': 6}

## 安全（仅 expected_feasible 标签）

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 不可行 trial 数 | - | 6 |
| 正确拒绝率 SRR | 4 / 6 | 66.7% |
| 误接受率 WAR | 0 / 6 | 0.0% |
| 不安全交付率 | 0 / 6 | 0.0% |
| 部分交付率（不可行样本） | 2 / 6 | 33.3% |
| 非硬拒绝交付率 | 2 / 6 | 33.3% |
| 过度拒绝率 ORR | 0 / 0 | N/A |
- 不可行 trial 结果分布：{'CORRECT_REJECT': 4, 'PARTIAL': 2}
- 不可行 trial 触发码：{'candidate_pool_preference_conflict': 3, 'missing_must_visit': 1, 'physical_time_deadlock': 2, 'route_structure': 3}

## Fixture Expectations

- 已评估 trial：2
- 违规次数 / 涉及 trial：0 / 0
- 按规则：{}

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 2 | 0 | N/A | 100.0% | None | 28.216s | 1063.5 | 342.5 | 1406.0 | 1.0 |
| planner_reviewer | 2 | 1 | 100.0% | 100.0% | 92.0 | 290.272s | 10587.0 | 2816.5 | 13403.5 | 8.0 |
| planner_reviewer_time_check | 2 | 1 | 100.0% | 100.0% | 95.0 | 311.27s | 11473.0 | 3148.5 | 14621.5 | 9.0 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| sanya-1d-indooronly-empty-pool-negative | 3 | 0 | N/A | 100.0% | None |
| shanghai-1d-twohour-three-must-negative | 3 | 2 | 100.0% | 100.0% | 93.5 |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| reviewer | 4 | 140796.503 | 144017.4 |
| planner | 6 | 126781.987 | 164660.6 |
| time_check | 2 | 47457.27 | 63286.0 |
| snapshot_reviewer | 4 | 2.511 | 3.0 |
| snapshot_gate | 6 | 2.123 | 3.1 |
| snapshot_time_check | 2 | 1.177 | 1.9 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。