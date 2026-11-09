# 自适应审核跳过：现状与放宽策略

> 口径：把真实草稿回放进 `route_risk_gate_node`，0 次模型调用
> 样本：30 份草稿（checkpoint 15，trial 15）

## 1. 现状门控（semantic_review=True）

- 跳过审核：**0 / 30（0.0%）**
- 误跳过（草稿自带 L0 或不可交付 L1）：0（N/A；缺陷已知 15 份）
- 反事实 Token 节省：0（占可比审核 Token 0.0%）

## 2. 放宽策略（semantic_review=False）

- 跳过审核：19 / 30（63.3%）
- 误跳过：0（0.0%）
- 被跳过草稿的缺陷分布：无（仅缺陷已知草稿可数）
- 反事实 Token 节省：124241（57.5%）
- 被跳过的草稿：['lijiang-5d-sunny-slowpace::planner_reviewer', 'lijiang-5d-sunny-slowpace::planner_reviewer_time_check', 'nanjing-3d-sunny-history::planner_only', 'nanjing-3d-sunny-history::planner_reviewer', 'nanjing-3d-sunny-history::planner_reviewer_time_check', 'shanghai-1d-sunny-nightlife::planner_reviewer', 'shanghai-1d-sunny-nightlife::planner_reviewer_time_check', 'nanjing-3d-tighthours-negative::planner_only', 'nanjing-3d-tighthours-negative::planner_reviewer', 'nanjing-3d-tighthours-negative::planner_reviewer_time_check', 'checkpoint::pair_01_lijiang-5d-sunny-slowpace_replace_indoor', 'checkpoint::pair_03_lijiang-5d-sunny-slowpace_remove_spot', 'checkpoint::pair_05_lijiang-5d-sunny-slowpace_cross_day', 'checkpoint::pair_06_lijiang-5d-sunny-slowpace_slow_pace', 'checkpoint::pair_09_nanjing-3d-sunny-history_slow_pace', 'checkpoint::pair_11_nanjing-3d-sunny-history_add_must_visit', 'checkpoint::pair_12_nanjing-3d-sunny-history_remove_spot', 'checkpoint::pair_13_nanjing-3d-tighthours-negative_add_must_visit', 'checkpoint::pair_14_nanjing-3d-tighthours-negative_remove_spot']

## 3. 逐草稿

| 草稿 | 来源 | 现状跳过 | 放宽跳过 | 审核增量 Token |
|---|---|---|---|---:|
| lijiang-5d-sunny-slowpace::planner_only | trial | False | False | 3141 |
| lijiang-5d-sunny-slowpace::planner_reviewer | trial | False | True | 3141 |
| lijiang-5d-sunny-slowpace::planner_reviewer_time_check | trial | False | True | 3141 |
| nanjing-3d-sunny-history::planner_only | trial | False | True | 9094 |
| nanjing-3d-sunny-history::planner_reviewer | trial | False | True | 9094 |
| nanjing-3d-sunny-history::planner_reviewer_time_check | trial | False | True | 9094 |
| shanghai-1d-sunny-nightlife::planner_only | trial | False | False | 20653 |
| shanghai-1d-sunny-nightlife::planner_reviewer | trial | False | True | 20653 |
| shanghai-1d-sunny-nightlife::planner_reviewer_time_check | trial | False | True | 20653 |
| nanjing-3d-tighthours-negative::planner_only | trial | False | True | 1905 |
| nanjing-3d-tighthours-negative::planner_reviewer | trial | False | True | 1905 |
| nanjing-3d-tighthours-negative::planner_reviewer_time_check | trial | False | True | 1905 |
| sanya-3d-allrain-outdoor-negative::planner_only | trial | False | False | 10861 |
| sanya-3d-allrain-outdoor-negative::planner_reviewer | trial | False | False | 10861 |
| sanya-3d-allrain-outdoor-negative::planner_reviewer_time_check | trial | False | False | 10861 |
| checkpoint::pair_01_lijiang-5d-sunny-slowpace_replace_indoor | checkpoint | False | True | 3141 |
| checkpoint::pair_02_lijiang-5d-sunny-slowpace_add_must_visit | checkpoint | False | False | 3141 |
| checkpoint::pair_03_lijiang-5d-sunny-slowpace_remove_spot | checkpoint | False | True | 3141 |
| checkpoint::pair_04_lijiang-5d-sunny-slowpace_change_time | checkpoint | False | False | 3141 |
| checkpoint::pair_05_lijiang-5d-sunny-slowpace_cross_day | checkpoint | False | True | 3141 |
| checkpoint::pair_06_lijiang-5d-sunny-slowpace_slow_pace | checkpoint | False | True | 3141 |
| checkpoint::pair_07_nanjing-3d-sunny-history_change_time | checkpoint | False | False | 9094 |
| checkpoint::pair_08_nanjing-3d-sunny-history_cross_day | checkpoint | False | False | 9094 |
| checkpoint::pair_09_nanjing-3d-sunny-history_slow_pace | checkpoint | False | True | 9094 |
| checkpoint::pair_10_nanjing-3d-sunny-history_replace_indoor | checkpoint | False | False | 9094 |
| checkpoint::pair_11_nanjing-3d-sunny-history_add_must_visit | checkpoint | False | True | 9094 |
| checkpoint::pair_12_nanjing-3d-sunny-history_remove_spot | checkpoint | False | True | 9094 |
| checkpoint::pair_13_nanjing-3d-tighthours-negative_add_must_visit | checkpoint | False | True | 1905 |
| checkpoint::pair_14_nanjing-3d-tighthours-negative_remove_spot | checkpoint | False | True | 1905 |
| checkpoint::pair_15_nanjing-3d-tighthours-negative_change_time | checkpoint | False | False | 1905 |

## 4. 结论

- 现状跳过率 **0%**：`preference_review` 对任何含偏好的 query 都强制升级审核，所以“自适应跳过低风险审核节省 Token”在当前实现下不可复现。
- 放宽 `semantic_review` 后才出现跳过（19/30）；误跳过 0.0%，需先确认可接受才能上线。
- 修复方向：把 `preference_review` 从“无条件强制升级”改为按偏好文本强度分级（如仅弱偏好走确定性门控），并用本脚本回归。

## 5. 读法

- 反事实节省不等于账单节省：跳过审核只省掉审核增量，主体规划成本不变。
- 同一 case 的多份草稿共用同一份审核增量，因此合计值对同 case 重复计数，只能当中上限。
- checkpoint 草稿没有 `l0_codes`，因此误跳过率只在 train 子集上有意义。
- 放宽策略不是产品默认；若要上线需另开一轮改门控并回归 HPR/ESR。