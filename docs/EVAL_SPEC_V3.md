# Travelmind 评测口径 v3（框架层）

> 版本：v3（2026-11-08）。v1/v2 的 spec、结果与原始 trial 保持冻结；本文件只定义增量。
> 框架验证阶段没有真实 planner / reviewer / judge 调用；真实 Judge、Reviewer 挑战与安全 trial 已单独执行，见 `docs/EVAL_RESULTS_V3_JUDGE.md`、`docs/EVAL_RESULTS_V3_REVIEWER.md`、`docs/EVAL_RESULTS_V3_SAFETY.md`。
> 数据目录：`evaluation/reports/v3-baseline/`、`evaluation/reports/v3-reviewer/`、`evaluation/judge/run-20261108/`、`evaluation/reviewer_challenge/run-20261108/`、`evaluation/trials/run-20261108-safety/`。

## 0. 适用范围与不变量

| 项 | v3 约定 |
|---|---|
| 资产 | 继承 v2 的 10 个 fixture，只新增 2 个安全负样本（`fixtures_v3/`） |
| 口径 | v3 新增 `delivered_plan` 语义、Safety、Judge、Reviewer 双口径、Expectations、Pass@K per case×mode |
| 冻结 | `EVAL_SPEC_V1.md`、`EVAL_RESULTS_V1.md`、`evaluation/trials/run-20261106/**`、`run-20261107-v2/**` 只读 |
| 生产代码 | 本轮不修改 `app/planning`；只度量，不改变产品行为 |
| 真实调用 | 框架验证为 0；真实 Judge 30 次 + Reviewer 12 次 + 安全 6 trial |

## 1. v3 资产

- `tests/eval/benchmark_v3.json` 登记 12 个 case：10 个 `fixture_source="v2"`，2 个 `fixture_source="v3"`。
- `tests/eval/fixtures_v3/` 只放新增负样本，不复制 v2 的 10 个文件。
- `harness.load_cases(version="v3")` 先加载 v2，再加载 v3；同 id 以 v3 为准。
- 每个 case 带 `fixture_sha256`；`tests/eval/assets.py:validate_version("v3")` 必须返回空列表。
- `tests/eval/frozen_assets_v1_v2.json` 冻结 v1/v2 指纹；`assets.frozen_mismatches()` 必须为空。

新增安全 case：

| case | expected_feasible | 不可行原因 |
|---|---|---|
| `shanghai-1d-twohour-three-must-negative` | false | 3 个必去点最短游览 180 分钟 > 120 分钟窗口；直线通勤下界 92.882 分钟进一步放大缺口 |
| `sanya-1d-indooronly-empty-pool-negative` | false | 用户要求只去室内，候选池 `indoor=true` 数量为 0 |

不可行判定不依赖 `allowed_outcomes` 反推，而由 `tests/eval/feasibility.py` 独立给出下界证据。只有下界已超窗或室内可行集为空才判 `INFEASIBLE`；其余为 `UNKNOWN`，不声称可行。

## 2. v3 交付语义（关键修正）

v1/v2 的 `plan_generated` 表示“草稿存在”。这会把产品已 `FAILED`（最终 `days=[]`）的记录记成 `HARD_FAIL`，无法衡量“正确拒绝”。

v3 起，只对 `--version v3` 生效：

| 字段 | 含义 |
|---|---|
| `draft_generated` | Planner 是否产出过非空草稿 |
| `plan_generated` | **是否真的交付**：status 非 `FAILED` 且交付路线非空 |
| `delivered_plan` | 与 v3 的 `plan_generated` 相同，显式字段 |
| `draft_soft_score` / `draft_oor` | 草稿诊断值，不进入交付质量分母 |
| `route_names` / `route_by_day` | 草稿路线，供诊断 |
| `delivered_route_names` / `delivered_route_by_day` | 交付路线，供 Judge 与 OOR 使用 |

`metrics.aggregate()` 的 `denominator_basis` 会显示 `plan_generated`（v1/v2 旧记录）或 `delivered_plan`（v3 新记录）；混合输入显示 `mixed`，报告不得混算。

## 3. Safety 指标

仅当 trial 记录带 `expected_feasible` 标签时计算；v1/v2 旧记录没有该字段，显示 `N/A`。

| 指标 | 公式 |
|---|---|
| `infeasible_trials` | `expected_feasible=false` 的有效 trial 数 |
| SRR 正确拒绝率 | `CORRECT_REJECT / infeasible_trials` |
| WAR 误接受率 | `WRONG_ACCEPT / infeasible_trials` |
| 不安全交付率 | `(WRONG_ACCEPT + HARD_FAIL) / infeasible_trials` |
| 部分交付率 | `PARTIAL / infeasible_trials` |
| 非硬拒绝交付率 | `(PARTIAL + HARD_FAIL + WRONG_ACCEPT) / infeasible_trials` |
| `feasible_trials` | `expected_feasible=true` 的有效 trial 数 |
| ORR 过度拒绝率 | `OVER_REJECT / feasible_trials` |
| `by_code` | 不可行 trial 的 `failure_codes` / `l0_codes` / `l1_codes` 计数 |

`CORRECT_REJECT` 仍沿用 v1 定义：未交付 + `failure_reasons` 含不可行码（`candidate_pool_preference_conflict` / `missing_must_visit` / `physical_time_deadlock`）。

**读法**：`WAR=0` 不等于安全；`PARTIAL` 仍可能交付带“时间不可行”警告的路线。必须同时报 `partial_delivery_rate` 与 `non_reject_delivery_rate`。2026-11-07 实跑结果见 `docs/EVAL_RESULTS_V3_SAFETY.md`。

**硬拒绝政策（2026-11-07 起）**：`physical_time_deadlock` 与 `candidate_pool_preference_conflict` 一律 `FAILED`，不再交付 `PARTIAL`；`route_after_review` / `route_after_time_check` 会短路到 finalize，连续两轮路线与缺陷码相同也会触发无进展熔断。安全样本回归见 `docs/EVAL_RESULTS_V3_SAFETY_HARDREJECT.md`。benchmark 的 `allowed_outcomes` 仍保留 `PARTIAL` 作为旧口径对照；当前实跑 `partial=0`，若回退会由 `partial_delivery_rate` 暴露。

## 4. 语义质量 Judge

### 4.1 Rubric

当前版本：`judge-rubric-v2` / `judge-prompt-v2`。

| 维度 | 权重 | 评价内容 |
|---|---:|---|
| `preference_fit` | 20 | 与偏好、习惯、必去点的契合 |
| `pacing` | 15 | 每天节奏与强度 |
| `geographic_coherence` | 15 | 地理顺序与折返 |
| `time_realism` | 20 | 时间、通勤、开放常识 |
| `completeness` | 15 | 信息完整、可直接执行 |
| `diversity_and_dining` | 15 | 多样性与餐饮/休息 |

每维 0–5；总分 = `sum(score/5 * weight)`，范围 0–100。每维必须给 `reason` 与 `evidence`（引用 Day/景点名）；缺失证据打 `evidence_missing` flag。

### 4.2 盲评

`build_payload()` 只输出：目的地、天数、日期、偏好、天气摘要、路线、候选池规模、`scope`。
禁止输出：`status`、`l0_codes`、`l1_codes`、`benchmark_label`、`actual_outcome`、`mode_*`、`soft_score`、`reviewer_approved`、模型名、`trial_id`。

`scope` 声明本次评测实际包含的字段，避免把 fixture 模式未运行的餐饮/交通当成规划缺陷：

| 字段 | 含义 |
|---|---|
| `meals` | 是否提供餐饮安排；false 时不因缺少餐饮扣分 |
| `transport_legs` | 是否提供路距/交通；false 时不因缺少交通扣分 |
| `live_info` | 是否提供门票/实时信息；false 时不因缺少实时信息扣分 |

### 4.3 Provider 与缓存

| provider | 行为 |
|---|---|
| `stub` | 确定性假评委，只验证管线；**不得当质量结果** |
| `replay` | 只读缓存；缺失即 `cache_miss`，不发请求 |
| `llm` | 复用 `app.llm.factory.build_structured_llm`；必须 `--allow-external-calls --max-calls N` |

缓存 key = `sha256(payload + rubric_version + prompt_version + model + judge_id + provider分区)`；`stub` 与 `runtime` 分区，`replay` 读取 runtime 缓存，防止 stub 分数污染真实结果。缓存命中不消耗预算；`--max-calls` 是硬上限，超出直接 `JudgeBudgetExceeded`。

报告同时给出 `judge_calls`（本次真实调用）与 `replayed_calls`（从真实缓存重放），两者不混算。

### 4.4 双评与校准

- `--k 2` 时报告 exact、within-1、mean abs diff、quadratic weighted kappa；同时报告逐 trial kappa 均值与合并 90 个维度对的 pooled kappa（小样本逐 trial kappa 不稳定）。
- 校准输入为 `evaluation/judge/calibration/labels_template.json`（人工总分/维度分）；计算 MAE、Spearman、分档一致率。
- 无人工标签时校准为 `N/A`，不得伪造。
- CLI 追加 `--calibration-labels evaluation/judge/calibration/labels_template.json` 即可把校准写入 `summary.json`。

## 5. Reviewer 可靠性

### 5.1 双口径

| 口径 | 适用 | 能力 |
|---|---|---|
| `snapshot_trace` | v3 新运行 | 每轮快照、审核决定、返工请求、路线签名、是否交付 |
| `proxy` | 现有 66+9+6 条旧记录 | 首版 L0、最终 L0、返工轮数 |

报告逐项标注 `source`，二者不混算。

### 5.2 指标定义

trace 口径：

- `review_request_rate` = 有返工请求的快照 / 全部快照；
- `rework_effective_rate` = 缺陷数下降的返工事件 / 返工事件；
- `rework_ignored_rate` = 路线签名不变且缺陷未减少的返工事件 / 返工事件；
- `rework_regression_rate` = 引入新 L0/L1 码的返工事件 / 返工事件；
- `clean_block_rate` = 零缺陷快照被审核打回 / 零缺陷快照；
- `delivered_with_defect_rate` = 交付快照仍有缺陷 / 已交付 trial。

proxy 口径：

- `rework_effective_rate` = 首版 L0 非空且最终 L0 空 / 首版 L0 非空且实际返工；
- `rework_ineffective_rate` = 首版 L0 非空且最终仍非空 / 同分母；
- `clean_block` 与 `regression` 无法从旧记录判断，固定 `N/A`。

**边界**：`clean_block` 只表示“审核打回了确定性零缺陷草稿”，是否真的误打回仍需 Judge 或人工语义复核。proxy 的 `rework_ineffective` 是“问题仍在”，不等于 Planner 忽略审核。

### 5.3 受控挑战集

`tests/eval/challenges_v3/` 有 6 个冻结挑战：clean control、unknown_poi、missing_must_visit、weather_outdoor、duplicate_poi、overpacked。每个挑战声明 `expected_verdict` 与 `expected_keywords`。

`reviewer_challenge.py` 记录 approve/reject、issues、opinion、关键词命中、耗时与 Token。本轮只做 dry-run 与 stub 测试；真实 Reviewer 调用需 `--allow-external-calls`。

## 6. Expectations 与 Pass@K

### 6.1 Fixture Expectations

`expectations.outdoor_on_bad_day_max` 已接入 v3 trial：

- 只对 `plan_generated=true` 的交付路线生效；
- 按 `travel_start_date + day-1` 对齐天气；
- `indoor is False` 才计室外，`null/unknown` 不计；
- 违规写入 `expectation_violations`，聚合为 `expectations.violations` / `by_rule`。

### 6.2 Pass@K

- 保留原 `pass_at_k`（按 case 池化）；
- 新增 `pass_at_k_by_case_mode`，按 `case_id__mode` 分组，字段 `k/match/pass_at_k/pass_pow_k/hpr_pass_at_k`；
- 仅组内 `k>=2` 才输出。

## 7. 运行协议

```powershell
# 全量测试（零成本）
..\.venv\Scripts\python.exe -m pytest -q tests

# v3 资产干跑（0 真实调用）
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 --dry-run

# 现有数据零成本基线
..\.venv\Scripts\python.exe -m tests.eval.aggregate_trials --dirs evaluation/trials/run-20261106/s1 evaluation/trials/run-20261106/s2 evaluation/trials/run-20261106/s3 evaluation/trials/run-20261107-v2 evaluation/trials/run-20261107-negative --out evaluation/reports/v3-baseline
..\.venv\Scripts\python.exe -m tests.eval.reviewer_reliability --dirs evaluation/trials/run-20261106/s1 evaluation/trials/run-20261106/s2 evaluation/trials/run-20261106/s3 evaluation/trials/run-20261107-v2 evaluation/trials/run-20261107-negative --out evaluation/reports/v3-reviewer

# Judge 管线自测（stub，仅验证流程）
..\.venv\Scripts\python.exe -m tests.eval.judge --trials evaluation/trials/run-20261107-v2 --version v2 --provider stub --k 2 --out evaluation/judge/selftest

# Reviewer 挑战集干跑
..\.venv\Scripts\python.exe -m tests.eval.reviewer_challenge --dry-run
```

真实运行（下一轮）：

```powershell
# 6 条安全负样本 trial（2 案例 × 3 模式）
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 --case shanghai-1d-twohour-three-must-negative --case sanya-1d-indooronly-empty-pool-negative --allow-external-calls --out evaluation/trials/run-20261108-safety

# 真实 Judge：15 条已有 route 的 trial（v2 9 + negative 6）
..\.venv\Scripts\python.exe -m tests.eval.judge --trials evaluation/trials/run-20261107-v2 --trials evaluation/trials/run-20261107-negative --version v2 --provider llm --k 2 --max-calls 40 --allow-external-calls --out evaluation/judge/run-20261108

# 真实 Reviewer 挑战
..\.venv\Scripts\python.exe -m tests.eval.reviewer_challenge --allow-external-calls --k 2 --out evaluation/reviewer_challenge/run-20261108
```

## 8. 不做的事

- 不修改 v1/v2 的 spec、结果或原始 trial；
- 不把 v3 的 `delivered_plan` 语义回填到 v1/v2；
- 不把 stub Judge 分数写进结论；
- 不用现有 66 条记录冒充 Judge 覆盖率（它们没有 `route_by_day`）；
- 不宣称 `physical_time_deadlock` 会被硬拒绝（它是 L1，产品会交付 PARTIAL）；
- 不把 proxy 的“问题仍在”写成“Planner 忽略审核”。