# Travelmind 评测口径 v1.2（已冻结）

> 冻结的是口径，不是结果；数据不达预期也如实保留。
> 冻结后不得修改判定码表与分母规则，调整需升版本。

## 0. 适用范围

| 项 | 说明 |
|---|---|
| 衡量对象 | Planner / Reviewer / Time Check 的规划质量与返工收益（fixture 子图） |
| 不衡量 | intent 抽取、有界 ReAct 候选补查、真实外部服务延迟 |
| 端到端切片 | 另设 3 例走 8766 SSE，仅报 P50/P95、Token、节点耗时 |
| 措辞 | 单图多角色编排；不写 Supervisor 协作 |

## 1. 判定基座

### 1.1 L0 硬约束码表（`quality.py:151`，锁定）

`unknown_poi`、`missing_must_visit`（`overflow_exempt` 豁免）、`route_structure`、
`candidate_pool_preference_conflict`、`indoor_constraint`、
`weather_outdoor_conflict`（仅 `rain_indoor_priority=true`）

### 1.2 L1 可修复码表

`invalid_time_slot`、`opening_time_conflict`、`closed_on_visit_day`、`duplicate_poi`、
`walking_constraint`、`commute_time_conflict`、`habit_constraint`、
`daily_capacity_exceeded`、`physical_time_deadlock`

### 1.3 快照语义（重要）

`append_route_snapshot` 的 `iteration = max(1, review_round)`，且同 iteration 覆盖：

- `snapshot_count = len(route_history)` = 不同 review_round 的数量，**不是**快照次数
- 同一轮内 route 不变 → `iteration=1` 的 L0 即首版草稿判定，FPR 可用
- `planning_revision_rounds = planner 进入次数 - 1`（由 runner 记录，不用快照数）
- 最终交付快照 = `choose_snapshot()` 选中项（**可能不是时间上最后一份**）

## 2. 实际结果与评价标签分离

### 2.1 actual_outcome（执行事实，写入 trial）

| 条件 | actual_outcome |
|---|---|
| 未生成路线 + 外部 API 故障 | `INFRA_FAILURE` |
| 未生成路线 + `NODE_TIMEOUT` | `TIMEOUT` |
| 未生成路线 + clarify | `CLARIFY` |
| 未生成路线 + 明确返回不可行及原因 | `CORRECT_REJECT` |
| 未生成路线 + 其他 | `FAILED` |
| 已生成路线 + L0 非空 | `HARD_FAIL` |
| 已生成路线 + L0 空 + status=SUCCESS | `SUCCESS` |
| 已生成路线 + L0 空 + status=SUCCESS_WITH_WARNINGS | `SUCCESS_WITH_WARNINGS` |
| 已生成路线 + L0 空 + status=PARTIAL_SUCCESS | `PARTIAL` |

`plan_generated = route 非空 且 days > 0`。
`CORRECT_REJECT` 要求 `failure_reasons` 或 `warnings` 含不可行码
（`candidate_pool_preference_conflict` / `missing_must_visit` / `physical_time_deadlock`）；
前 3 例人工复核一次，之后按规则自动判定。

### 2.2 benchmark_label（评价标签，不写入生产状态）

| 条件 | label |
|---|---|
| actual_outcome ∈ allowed_outcomes | `MATCH` |
| allowed ⊆ {PARTIAL, CORRECT_REJECT} 且 actual=SUCCESS | `WRONG_ACCEPT` |
| expect=success 且 actual ∈ {FAILED, CORRECT_REJECT, CLARIFY} | `OVER_REJECT` |
| actual=HARD_FAIL | `HARD_FAIL` |
| invalid_trial | `INVALID` |
| 其他 | `MISMATCH` |

`expected_outcome_match = (label == MATCH)`。

## 3. 指标定义

有效试验：`effective_trials = 全部 trial - invalid_trial`。
`InvalidRate = invalid_trial / 全部 trial`（单报，不进入质量分母）。

### P0 交付与预期匹配（分母 = effective_trials）

| 指标 | 公式 |
|---|---|
| 完整交付率 FDR | (SUCCESS + SUCCESS_WITH_WARNINGS) / effective_trials |
| 部分交付率 PDR | PARTIAL / effective_trials |
| 预期结果匹配率 OMR | label=MATCH / effective_trials |

外部 API 故障、Agent 超时、clarify 均属有效试验（计入失败），不属于 invalid。

### P0 规划质量

| 指标 | 公式 | 分母 |
|---|---|---|
| 硬约束通过率 HPR | plan_generated ∧ hard_pass / plan_generated 的有效 trial | 无产出不计入 |
| 首轮通过率 FPR | iteration=1 快照 L0 为空的 trial / plan_generated 的有效 trial | |
| 池外实体率 OOR | 池外引用数 / POI 引用总数（报 M/N） | `unknown_spots()` |
| 必去满足率 MSR | 全部 must_visit 出现的有效 trial / 启用 must_visit 的有效 trial | 无规划的 trial 也计入分母并视为未满足 |
| 避开满足率 MAR | v1 无 must_avoid → **N/A**（不报 0%） | |
| 软质量分 SS | 最终交付快照 `soft_score`（0–100）+ 六维 | |

名称匹配：`normalize_poi_name()` + `poi_name_matches()`。

### P0 可靠性

| 指标 | 公式 |
|---|---|
| 返工修复率 RRR | (首版 L0 非空 ∧ 最终交付 L0 空 ∧ planning_revision_rounds≥1) / (首版 L0 非空 ∧ planning_revision_rounds≥1)，仅有效 trial |
| 平均规划修订轮数 | mean(planning_revision_rounds)；另报 review_round / time_check_round / snapshot_count |
| Outcome Pass@K | K 次中 ≥1 次 label=MATCH |
| Outcome Pass^K | K 次全部 label=MATCH |
| HPR Pass@K | 仅 expect=success 案例：K 次中 ≥1 次 plan_generated ∧ hard_pass |

### P1 性能与成本

| 指标 | 来源 | 备注 |
|---|---|---|
| 端到端 P50/P95 | trial 墙钟 | n<20 只报 median + min/max，P95 标"样本不足" |
| 节点耗时 | `agent_runs` + SSE stage | 报 P50 与最慢 3 个节点 |
| Token | `llm_usage.py` | 标注 estimated |
| LLM 调用次数 | `llm_usage.py` | 区分首次与重试 |
| 工具调用（代理） | `candidate_api_calls`、`route_leg_count` 分开记录、不相加 | 不称精确 Tool Calls |

## 4. 测试集 v1（10 例）

| # | fixture | allowed_outcomes |
|---|---|---|
| 1 | nanjing-3d-sunny-history | [SUCCESS, SUCCESS_WITH_WARNINGS] |
| 2 | nanjing-3d-singlerain-history | [SUCCESS, SUCCESS_WITH_WARNINGS] |
| 3 | nanjing-3d-tighthours-negative | [PARTIAL, CORRECT_REJECT] |
| 4 | shanghai-1d-sunny-nightlife | [SUCCESS, SUCCESS_WITH_WARNINGS] |
| 5 | shanghai-3d-smallpool-negative | [SUCCESS_WITH_WARNINGS, PARTIAL] |
| 6 | shanghai-3d-beyond-forecast | [SUCCESS, SUCCESS_WITH_WARNINGS] |
| 7 | lijiang-5d-sunny-slowpace | [SUCCESS, SUCCESS_WITH_WARNINGS] |
| 8 | lijiang-3d-allrain-history | [SUCCESS, SUCCESS_WITH_WARNINGS, PARTIAL] |
| 9 | sanya-3d-allrain-outdoor-negative | [PARTIAL, CORRECT_REJECT] |
| 10 | jingdezhen-3d-sunny-history | [SUCCESS, SUCCESS_WITH_WARNINGS] |

must_visit（已核实存在于 fixture.pois）：

| 案例 | must_visit |
|---|---|
| nanjing-3d-sunny-history | `玄武湖景区` |
| shanghai-1d-sunny-nightlife | `上海海洋水族馆` |
| lijiang-5d-sunny-slowpace | `束河古镇` |

其余案例 must_visit 留空；must_avoid 全部留空（v1 不引入）。
`PARTIAL` 验收条件：plan_generated=true 且 warnings 非空。

## 5. 运行协议与 Harness 强制要求

### 5.1 模式

| 模式 | 强制节点 |
|---|---|
| A `planner_only` | planner |
| B `planner_reviewer` | planner + reviewer |
| C `planner_reviewer_time_check` | planner + reviewer + time_check |

### 5.2 冻结前检查结果

| 检查 | 结果 |
|---|---|
| 绕过生产 risk gate | ✅ mini-graph 无 risk_gate 节点 |
| B/C 必执行 Reviewer | ✅ planner→reviewer 直连 |
| 必执行 Time Check | ❌ `route_after_review` 在 clean 时返回 finalize（`graph.py:130-134`） |
| 轮次快照 | ❌ harness 未挂 snapshot 节点 |

### 5.3 实现阶段强制验收

1. A/B/C 均挂 snapshot 节点：`planner→snapshot_gate`、`reviewer→snapshot_reviewer`、`time_check→snapshot_time_check`。
2. snapshot 节点必须纯记录：只返回 `route_history` / `score_info`，不得修改 route、approved、review_round 或路由条件。
3. C 组强制 `reviewer→time_check`（受 `max_time_check_rounds` 限制），不沿用生产跳过逻辑。
4. 记录 `mode_requested` / `mode_effective` / `nodes_entered`；C 组未进 time_check → `invalid_trial`。
5. 首版快照与最终交付快照可稳定获取（首版取 iteration=1，最终取 `choose_snapshot`）。
6. 用固定 route 的 stub planner 验证：挂 snapshot 前后状态字段与路由路径一致。

### 5.4 invalid_trial 判定

- `mode_effective ≠ mode_requested`
- C 组 `nodes_entered` 不含 `time_check`
- 首版快照缺失 / fixture 校验失败 / 记录字段缺失
- Harness 异常

## 6. 阶段与耗时

| 阶段 | 规模 | 目的 | 理论耗时 |
|---|---|---|---|
| S1 | 3 例 × 3 模式 × 1 = 9 | 流程与字段验证 | 36–108 分钟 |
| S2 | 10 例 × 3 模式 × 1 = 30（先 5 例 15 次） | 首版消融 | 2–6 小时 |
| S3 | 3 例 × 3 模式 × 3 = 27 | Outcome Pass@3 / Pass^3 | 1.8–5.4 小时 |
| 合计 | 66 | | 4.4–13.2 小时 |

先用 S1 实测中位耗时，再排 S2/S3，不预先承诺固定耗时。
S1 选样：nanjing-3d-sunny-history、nanjing-3d-tighthours-negative、sanya-3d-allrain-outdoor-negative。
S3 只作代表性案例重复性验证，不外推整体可靠性。

## 7. Trial 记录字段

```json
{
  "trial_id": "", "case_id": "",
  "mode_requested": "C", "mode_effective": "planner_reviewer_time_check",
  "nodes_entered": ["planner", "reviewer", "time_check"],
  "invalid_trial": false, "invalid_reason": null,

  "plan_generated": true,
  "actual_outcome": "SUCCESS",
  "benchmark_label": "MATCH",
  "expected_outcome_match": true,

  "hard_pass": true, "l0_codes": [], "l1_codes": [],
  "first_draft_l0": [],
  "final_delivered_iteration": 2,

  "planning_revision_rounds": 1,
  "review_round": 1, "time_check_round": 0, "snapshot_count": 2,

  "soft_score": 88.0,
  "oor": {"outside": 0, "total": 12},
  "must_visit_ok": true, "must_avoid_ok": null,

  "latency_s": 0.0, "node_latency_ms": {},
  "input_tokens_est": 0, "output_tokens_est": 0, "llm_calls": 0,
  "candidate_api_calls": 0, "route_leg_count": 0,

  "error_kind": null, "error": null
}
```

## 8. 报告与措辞边界

- 池外实体率写成："N 次任务共检查 M 个 POI 引用，候选池外实体 0 个"。
- 单次运行只作诊断；稳定性只在 S3 的 Outcome Pass@3 / Pass^3 中陈述。
- n<20 不重点报 P95。
- 不引用 TravelMind-Agent / FloatTrip 的历史数字。
- 质量提升必须标注"相对哪一组、同一 fixture、k 次中的几次"。
- MAR 在 v1 报 N/A。

## 9. 验收（DoD）

1. S1 字段齐全率 100%，0 崩溃，0 未归类异常。
2. 三组 `route_history` 非空；首版与最终交付快照可获取。
3. C 组每条有效 trial 的 `nodes_entered` 含 time_check。
4. 同 fixture + 同模式重跑，`hard_pass` 判定一致。
5. 报告同时给出分子/分母/样本数；FDR/PDR/OMR 用 effective 分母，InvalidRate 单报。
6. RRR 使用 `choose_snapshot` 的最终交付快照，不使用"时间最后一份"。
7. 消融表能回答：规则/审核/时间复核各拦下多少、修复多少、代价多少 Token 与秒数。

## 10. 已确认决策

| 项 | 决定 |
|---|---|
| 10 个 fixture | 保留 |
| must_visit | 南京/上海/丽江 3 例，POI 已冻结 |
| A/B/C | 确认，snapshot 与 C 组 time_check 强制 |
| L0/L1 码表 | 锁定 |
| CORRECT_REJECT | 仅"无路线 + 明确不可行原因" |
| WRONG_ACCEPT | 仅评价标签，不写入生产状态 |
| 返工轮数 | 按 planner 进入次数 |
| invalid_trial | 独立分母，不进质量指标 |
| MAR | N/A |
| Token | 估算并注明 |
| HTTP 工具计数 | v1 暂缓 |
