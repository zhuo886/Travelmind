# 真实 Judge 结果（2026-11-07）

> 脚本：`python -m tests.eval.judge`
> 数据：`evaluation/judge/run-20261108/`
> 口径：`docs/EVAL_SPEC_V3.md`，`judge-rubric-v2` / `judge-prompt-v2`
> 模型：`glm-4.5-flash`，`temperature=0`，`k=2`

## 1. 运行概况

| 项 | 值 |
|---|---:|
| 评分对象 | 15 条已有 `route_by_day` 的 trial（v2 9 + negative 6） |
| 有效评分 | 15 / 15 |
| 真实 Judge 调用 | 30（每条 2 评委） |
| 估算 Token | 37,126 |
| 错误 | 0 |
| 缓存重放 | 30（重算报告未新增调用） |
| 总分均值 | **78.73 / 100** |
| 双评 kappa（逐 trial 均值） | 0.5088 |
| 双评 kappa（合并 90 个维度对） | **0.5975** |

## 2. 维度结果

| 维度 | 均值（0–5） | 说明 |
|---|---:|---|
| `preference_fit` | 3.867 | 偏好契合整体尚可，但有 10 次 `preference_mismatch` |
| `pacing` | 3.933 | 节奏多数合理 |
| `geographic_coherence` | 3.667 | 9 次 `geographic_inefficiency`，是第二高频问题 |
| `time_realism` | 4.267 | 最高分维度 |
| `completeness` | 4.167 | 仅评路线信息，不要求餐饮/交通 |
| `diversity_and_dining` | 3.633 | 最低分维度，主要是景点类型重复 |

## 3. 按案例

| case | 均值 | 备注 |
|---|---:|---|
| `nanjing-3d-sunny-history` | 84.5 | 最高 |
| `lijiang-5d-sunny-slowpace` | 81.67 | 慢节奏整体合理 |
| `nanjing-3d-tighthours-negative` | 80.0 | 复核后确认实际可行 |
| `shanghai-1d-sunny-nightlife` | 79.0 | 1 天路线，时间现实性较好 |
| `sanya-3d-allrain-outdoor-negative` | **68.5** | 全程雨 + 全露天，最低 |

低分 trial（<60）：`05b4753…`（Sanya）53.0。Judge 的主要意见是：

- Day1 南山片区偏宗教文化，与“海滨自然”偏好不完全一致；
- 每天固定 3.5 小时块、没有缓冲，雨天节奏不现实；
- Day2/Day3 重复海滩类景点，多样性不足；
- 时间安排未考虑景点间通勤与雨天延误。

该 trial 也是唯一一个 `pacing` 与 `time_realism` 同时低于 3 的样本。

## 4. Judge flags

| flag | 次数（30 次评分） |
|---|---:|
| `preference_mismatch` | 10 |
| `geographic_inefficiency` | 9 |
| `bad_weather_all_days` | 7 |
| `missing_transport` | 2 |
| `limited_diversity` | 1 |
| `evidence_missing` | 1 |
| `other` | 13 |

说明：

- `missing_transport` 在 scope 声明 `transport_legs=false` 后已从 14 次降到 2 次，说明 scope 生效；仍有 2 次是模型未完全遵守范围，只作诊断。
- `missing_dining` 在 v2 中完全消失，因为 fixture 模式不跑餐饮，rubric v2 明确不因缺少餐饮扣分。
- `other` 是未能映射到固定集合的自由文本 flag，只作观察，不进入质量结论。

## 5. 与 soft_score 的关系

Judge 与生产 `soft_score` 不是同一把尺子：

- `soft_score` 是确定性 100 分制（偏好/节奏/地理/天气/多样性），用于快照选择；
- Judge 是语义评委，覆盖“通勤时间是否现实、地理是否折返、偏好是否真的契合”等 `soft_score` 难以表达的问题；
- 两者不能相加，也不能互相替代。本轮没有做两者的相关性分析，n=15 也不足以做。

## 6. 过程修正（结果可复核的前提）

本次真实 Judge 前两次运行被废弃，原因已写入代码与测试：

1. **stub 缓存污染**：缓存 key 未区分 provider，真实 Judge 前 9 条直接命中 stub 的 81.5 分。已改为 `provider` 分区（`stub` vs `runtime`），并补测试。
2. **rubric v1 不公平**：fixture 模式不跑餐饮与路距节点，Judge 却把“缺餐饮/交通”大量记为缺陷（`missing_dining` 23 次、`missing_transport` 14 次），导致总分被系统性压低到 64.03。已升级 `judge-rubric-v2`，在 payload 增加 `scope` 并明确不因未提供的字段扣分。

废弃运行的分数不作为结果。最终结果只来自 rubric v2 / prompt v2 的 30 次真实调用。

## 7. 边界

- n=15，且不是 v1 的 30 条主消融；不能外推整体质量。
- 没有人工校准标签，MAE / Spearman 仍为 N/A；kappa 只能说明两位模型评委的一致性，不等于与人类一致。
- 单一模型、单一温度；换模型需要重新跑，不能直接横比。
- route-only：没有餐饮、交通、门票、实时信息，`completeness` 与 `diversity_and_dining` 只按路线范围解释。
- `glm-4.5-flash` 的 37,126 Token 是估算值，不是账单。

## 8. 下一步

1. 人工抽 5–10 条填 `evaluation/judge/calibration/labels_template.json`，跑一次校准（MAE / Spearman / 分档一致率）。
2. 再决定是否扩到 30 条主消融；扩样前先冻结 rubric v2。
3. 转入真实 Reviewer 挑战（6 × k=2）与 v3 安全负样本（2 × 3 模式）。
4. 不把本轮 78.73 写成“产品整体质量”或“比 soft_score 更好”。