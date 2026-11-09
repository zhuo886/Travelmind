# Reviewer 可靠性

- 记录总数：81
- 口径：snapshot_trace 与 proxy 分开统计，不混算。

## snapshot_trace

- N/A：现有记录没有每轮快照。

## proxy

- trial：81；有返工尝试：24；首版 L0 且返工：6

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 返工修复率 | 6 / 6 | 100.0% |
| 返工未修复率 | 0 / 6 | 0.0% |
| 交付仍带缺陷率 | 12 / 78 | 15.4% |
| 误接受率 WRONG_ACCEPT | 4 / 81 | 4.9% |
| 过度拒绝率 OVER_REJECT | 0 / 81 | 0.0% |

> proxy 的 rework_ineffective 是“问题仍在”，不等于 Planner 忽略审核；clean_block 与 regression 无法从旧记录判断。

## 边界

- clean_block 只表示“审核打回了确定性零缺陷草稿”，是否真的误打回仍需 Judge 或人工语义复核。
- proxy 的返工分母只包含“首版 L0 非空且实际返工”的 trial，不能当整体审核收益。
- 本报告是零成本离线基线，不包含任何真实 Reviewer 调用。