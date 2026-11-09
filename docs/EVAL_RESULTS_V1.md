# Travelmind 评测结果 v1（2026-11-06）

> 口径见 [EVAL_SPEC_V1.md](./EVAL_SPEC_V1.md)。原始记录：
> `evaluation/trials/run-20261106/{s1,s2,s3,final}`。
> 结论只覆盖 Planner / Reviewer / Time Check 的规划质量，不含 intent 与候选补查。

## 0. 运行概况

| 项 | 值 |
|---|---|
| 冻结用例 | 10 例（5 城 × 1/3/5 天 × 晴/雨/超预报/小池/紧时段） |
| 模式 | A `planner_only` / B `planner_reviewer` / C `planner_reviewer_time_check` |
| 总 trial | **66**（S1 9 + S2 30 + S3 27） |
| 无效 trial | **0**（mode_effective 一致、C 组均执行 time_check、首版快照可取） |
| 模型 | glm-4.5-flash（temperature=0） |
| 外部故障 | 最终入库记录 0；另有 16 次并发 429 尝试被剔除，串行重跑后替代（见 `evaluation/trials/run-20261106/INCIDENTS.md`） |

## 1. 总体指标

| 指标 | 分子 / 分母 | 值 |
|---|---|---|
| 完整交付率 FDR | 54 / 66 | 81.8% |
| 部分交付率 PDR | 10 / 66 | 15.2% |
| 预期结果匹配率 OMR | 38 / 66 | 57.6% |
| 硬约束通过率 HPR | 64 / 66 | **97.0%** |
| 首轮通过率 FPR | 60 / 66 | 90.9% |
| 必去（benchmark 指定）命中率 MSR | 24 / 30 | 80.0% |
| 返工修复率 RRR | 4 / 4 | **100%** |
| 池外实体率 OOR | 2 / 405 个引用 | **0.49%** |
| 软质量分均值 | 66 次 | 83.07 / 100 |

- 端到端耗时：median **202.2s**，min 35.4s，max 600.3s，P95 **476.4s**（n=66）。
- 平均规划修订轮数 0.52；平均快照数 1.52。
- 结果分布：`SUCCESS_WITH_WARNINGS` 45、`PARTIAL` 10、`SUCCESS` 9、`HARD_FAIL` 2。

## 2. A/B/C 消融（每组 22 次）

| 指标 | A 单轮 Planner | B + Reviewer | C + Time Check |
|---|---|---|---|
| 硬约束通过率 HPR | 90.9% | 100% | 100% |
| 预期匹配率 OMR | 36.4% | **68.2%** | **68.2%** |
| 软质量均分 | 77.19 | 84.50 | **87.53** |
| 中位耗时 | 66.5s | 256.1s | 294.2s |
| 平均输入 Token | 2,454 | 9,567 | 9,425 |
| 平均 LLM 调用 | 1.18 | 3.91 | 4.68 |

解读：

- **Reviewer 是主要收益来源**：OMR +31.8 个百分点、软质量 +7.3，代价是 Token ×3.9、延迟 ×3.8。
- **Time Check 是边际优化**：软质量再 +3.0，OMR 不变，Token 基本持平，延迟 +38s。
- A 组有 2 次 L0 硬失败（池外实体），B/C 组为 0 —— 审核闭环确实消除了硬约束漏检。

## 3. S3 重复性（3 例 × 3 模式 × k=3 = 27 次）

| 案例 | A pass@3 / pass^3 | B pass@3 / pass^3 | C pass@3 / pass^3 |
|---|---|---|---|
| nanjing-3d-sunny-history | 是 / 否 | 是 / 是 | 是 / 是 |
| shanghai-1d-sunny-nightlife | 否 / 否 | 是 / 是 | 是 / 是 |
| sanya-3d-allrain-outdoor-negative | 否 / 否 | 否 / 否 | 否 / 否 |

- 成功型案例（南京 + 上海）：A 组 pass@3 **1/2**、pass^3 **0/2**；B/C 组 pass@3 **2/2**、pass^3 **2/2**。
- 说明 Reviewer 不仅抬高单次能力，也消除单次抖动；HPR Pass@3 在全部 9 个 case×mode 组均为是。
- 三亚负样本三组全部未命中：系统在"应当拒绝/降级"时仍持续给出 `SUCCESS_WITH_WARNINGS`，这是当前最大产品缺口，不应包装成稳定性问题。

## 3.1 P1 节点耗时（66 次，中位 / 最大）

| 节点 | n | 中位 | 最大 |
|---|---|---|---|
| reviewer | 44 | 100.6s | 303.9s |
| planner | 66 | 85.3s | 313.1s |
| time_check | 22 | 65.9s | 267.4s |
| snapshot_*（纯记录） | 66/44/22 | 1.5–2.6ms | 24.9ms |

fixture 模式不含候选补查与 `route_distance_check`，因此 `candidate_api_calls` 与 `route_leg_count` 均为 0，属预期，不代表生产链路无工具调用。

## 4. 诚实边界（写简历时保留）

1. `must_visit` 是 Benchmark 元数据，**没有注入 fixture query**；MSR 是"benchmark 指定景点命中率"，不是"用户点名必须满足率"。
2. fixture 模式跳过 intent 与有界 ReAct 候选补查，因此不衡量端到端成功率；端到端只有此前 275.8s / 278.1s 的单次冒烟记录。
3. `glm-4.5-flash` 单次波动 35–600 秒，延迟指标只代表当前模型与账户条件。
4. `REPORT.md` 里的 Pass@K 按案例池化（k=3–15）；稳定性结论应引用上表 S3-only 数据。
5. OOR 0.49% 表述为"66 次任务共检查 405 个 POI 引用，池外实体 2 个"，不写"彻底解决幻觉"。

## 5. 简历可用句式（数字均已实测）

- 构建 10 例冻结评测集（5 城 × 1/3/5 天 × 晴/雨/超预报/小池/紧时段，真实高德 POI），完成 **66 次真实运行、0 无效试验**，确定性硬约束通过率 **97.0%**，候选池外实体 **2/405（0.49%）**。
- 设计 Planner→Reviewer→Time Check 三组消融（每组 22 次）：预期匹配率 **36.4% → 68.2%**、软质量 **77.2 → 84.5**，代价 Token ×3.9、延迟 ×3.8；Time Check 再提升软质量至 **87.5**，Token 基本不变。
- 重复性实验（成功型案例）：单轮 Planner pass@3 **50%** / pass^3 **0%**，加入审核闭环后 pass@3 **100%** / pass^3 **100%**，同时提升能力与稳定性。
- 评测工程：self-built harness 绕过生产 risk gate 强制 A/B/C 模式，snapshot 纯记录不改变规划结果；限流按 60/120/180s 退避后恢复，避免把账户限流误记为 Agent 失败。
