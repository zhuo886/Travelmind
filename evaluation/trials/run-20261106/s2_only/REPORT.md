# Travelmind 评测报告

- 全部 trial：30；有效：30；invalid：0

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 24 / 30 | 80.0% |
| 部分交付率 PDR | 6 / 30 | 20.0% |
| 预期结果匹配率 OMR | 20 / 30 | 66.7% |
| 硬约束通过率 HPR | 30 / 30 | 100.0% |
| 首轮通过率 FPR | 30 / 30 | 100.0% |
| 必去满足率 MSR | 8 / 9 | 88.9% |
| 返工修复率 RRR | 0 / 0 | N/A |

- 池外实体率：0 / 201 个引用
- 平均规划修订轮数：0.6；平均快照数：1.6
- 软质量分均值：83.04（n=30）
- 端到端耗时 median/min/max/P95：207.476/55.195/600.287/476.449s（n=30）
- 结果分布：{'PARTIAL': 6, 'SUCCESS': 6, 'SUCCESS_WITH_WARNINGS': 18}
- 评价标签分布：{'MATCH': 20, 'MISMATCH': 9, 'WRONG_ACCEPT': 1}

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 10 | 10 | 100.0% | 40.0% | 78.17 | 62.687s | 2005.6 | 1225.2 | 3230.8 | 1.0 |
| planner_reviewer | 10 | 10 | 100.0% | 80.0% | 85.2 | 258.448s | 9610.7 | 2675.8 | 12286.5 | 4.1 |
| planner_reviewer_time_check | 10 | 10 | 100.0% | 80.0% | 85.77 | 300.595s | 10200.8 | 3078.9 | 13279.7 | 5.1 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| jingdezhen-3d-sunny-history | 3 | 3 | 100.0% | 100.0% | 94.67 |
| lijiang-3d-allrain-history | 3 | 3 | 100.0% | 100.0% | 63.95 |
| lijiang-5d-sunny-slowpace | 3 | 3 | 100.0% | 66.7% | 92.33 |
| nanjing-3d-singlerain-history | 3 | 3 | 100.0% | 66.7% | 81.17 |
| nanjing-3d-sunny-history | 3 | 3 | 100.0% | 66.7% | 93.67 |
| nanjing-3d-tighthours-negative | 3 | 3 | 100.0% | 0.0% | 88.67 |
| sanya-3d-allrain-outdoor-negative | 3 | 3 | 100.0% | 0.0% | 62.0 |
| shanghai-1d-sunny-nightlife | 3 | 3 | 100.0% | 100.0% | 90.33 |
| shanghai-3d-beyond-forecast | 3 | 3 | 100.0% | 66.7% | 84.0 |
| shanghai-3d-smallpool-negative | 3 | 3 | 100.0% | 100.0% | 79.67 |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| reviewer | 20 | 100567.796 | 303865.5 |
| planner | 30 | 84256.235 | 280632.6 |
| time_check | 10 | 71706.296 | 241633.1 |
| snapshot_reviewer | 20 | 3.307 | 22.4 |
| snapshot_gate | 30 | 2.138 | 10.4 |
| snapshot_time_check | 10 | 1.511 | 6.2 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。