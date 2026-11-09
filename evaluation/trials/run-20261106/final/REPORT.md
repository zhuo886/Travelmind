# Travelmind 评测报告

- 全部 trial：66；有效：66；invalid：0

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 54 / 66 | 81.8% |
| 部分交付率 PDR | 10 / 66 | 15.2% |
| 预期结果匹配率 OMR | 38 / 66 | 57.6% |
| 硬约束通过率 HPR | 64 / 66 | 97.0% |
| 首轮通过率 FPR | 60 / 66 | 90.9% |
| 必去满足率 MSR | 24 / 30 | 80.0% |
| 返工修复率 RRR | 4 / 4 | 100.0% |

- 池外实体率：2 / 405 个引用
- 平均规划修订轮数：0.515；平均快照数：1.515
- 软质量分均值：83.07（n=66）
- 端到端耗时 median/min/max/P95：202.221/35.4/600.287/476.449s（n=66）
- 结果分布：{'HARD_FAIL': 2, 'PARTIAL': 10, 'SUCCESS': 9, 'SUCCESS_WITH_WARNINGS': 45}
- 评价标签分布：{'HARD_FAIL': 2, 'MATCH': 38, 'MISMATCH': 24, 'WRONG_ACCEPT': 2}

## 按模式对照（A/B/C）

| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |
|---|---|---|---|---|---|---|---|---|---|---|
| planner_only | 22 | 22 | 90.9% | 36.4% | 77.19 | 66.549s | 2454.0 | 1181.4 | 3635.4 | 1.18 |
| planner_reviewer | 22 | 22 | 100.0% | 68.2% | 84.5 | 256.05s | 9566.7 | 2493.0 | 12059.8 | 3.91 |
| planner_reviewer_time_check | 22 | 22 | 100.0% | 68.2% | 87.53 | 294.15s | 9424.7 | 2759.9 | 12184.6 | 4.68 |

## 按案例

| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |
|---|---|---|---|---|---|
| nanjing-3d-sunny-history | 15 | 15 | 100.0% | 86.7% | 92.73 |
| nanjing-3d-tighthours-negative | 6 | 6 | 100.0% | 0.0% | 91.33 |
| sanya-3d-allrain-outdoor-negative | 15 | 15 | 93.3% | 6.7% | 65.17 |
| jingdezhen-3d-sunny-history | 3 | 3 | 100.0% | 100.0% | 94.67 |
| lijiang-3d-allrain-history | 3 | 3 | 100.0% | 100.0% | 63.95 |
| lijiang-5d-sunny-slowpace | 3 | 3 | 100.0% | 66.7% | 92.33 |
| nanjing-3d-singlerain-history | 3 | 3 | 100.0% | 66.7% | 81.17 |
| shanghai-1d-sunny-nightlife | 12 | 12 | 91.7% | 75.0% | 89.92 |
| shanghai-3d-beyond-forecast | 3 | 3 | 100.0% | 66.7% | 84.0 |
| shanghai-3d-smallpool-negative | 3 | 3 | 100.0% | 100.0% | 79.67 |

## 节点耗时（中位 / 最大，毫秒）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| reviewer | 44 | 100567.796 | 303865.5 |
| planner | 66 | 85319.416 | 313094.3 |
| time_check | 22 | 65938.765 | 267439.7 |
| snapshot_reviewer | 44 | 2.619 | 24.9 |
| snapshot_gate | 66 | 2.586 | 19.7 |
| snapshot_time_check | 22 | 1.511 | 6.2 |

## 工具调用（代理指标，不相加）

- 候选补查 API 调用均值：0.0（fixture 模式跳过候选补查，0 属预期）
- 路距 leg 数均值：0.0（fixture 模式不含 route_distance_check，0 属预期）

> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。