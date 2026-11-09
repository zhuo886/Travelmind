# Travelmind 评测口径 v2

> 版本：v2（2026-11-06）。v1 口径与结果保持冻结，本文件只定义增量变化。
> 数据目录：`evaluation/trials/run-20261107-v2/`。

## 0. 与 v1 的差异（只列变化）

| 项 | v1 | v2 |
|---|---|---|
| `must_visit` | benchmark 元数据，未进入 fixture query | 3 个案例的 query 写入"一定要去“…”"，由 `constraints.active_must_visit()` 真实抽取 |
| 南京 `nanjing-3d-tighthours-negative` | `[PARTIAL, CORRECT_REJECT]` | `[SUCCESS, SUCCESS_WITH_WARNINGS]`（复核确认样本实际可行） |
| 天气降级 | 仅 `rain_indoor_priority=true` 时 `weather_outdoor_conflict`（L0） | 新增 L1 `weather_exposure_conflict`：全程恶劣天气且所有已排景点均室外 → `PARTIAL_SUCCESS` |
| 资产 | `tests/eval/fixtures/`、`benchmark_v1.json` | 新增 `tests/eval/fixtures_v2/`、`benchmark_v2.json`；v1 资产不改 |
| 运行入口 | `run_trials`（仅 v1） | `run_trials --version v2` |

## 1. must_visit 注入

3 个案例的 query 追加一句（保留原 query 内容）：

| 案例 | 追加内容 |
|---|---|
| nanjing-3d-sunny-history | `一定要去“玄武湖景区”。` |
| shanghai-1d-sunny-nightlife | `一定要去“上海海洋水族馆”。` |
| lijiang-5d-sunny-slowpace | `一定要去“束河古镇”。` |

触发链：`extract_explicit_place_requests()`（触发词 `一定要去` + 引号 POI）→ `active_must_visit()` → `capacity_policy()` → `hard_constraint_report()` 的 L0 `missing_must_visit`。

验收要求：v2 的 3 个案例在 trial 记录中 `must_visit_expected` 非空；A 组若漏排，必须出现 `l0_codes=["missing_must_visit"]` 且 `actual_outcome=HARD_FAIL`。这是 v2 与 v1 最关键的差别。

## 2. 天气降级规则（新 L1）

`app/planning/quality.py:weather_exposure_violations()`

触发条件（全部满足）：

1. `weather_forecast` 非空；
2. 所有旅行日 `is_bad=true`；
3. 路线非空且至少一个景点；
4. 所有已排景点的 `pois[...].indoor is False`。

效果：`choose_snapshot()` 落入 tier2 → `PARTIAL_SUCCESS`，并返回具体提醒。

作用域：只覆盖"全程雨 + 全室外"。单日降雨、当天含室内景点、天气未知（超出预报）均不触发。离线影响面已核对：

| fixture | 全程恶劣 | indoor 数/池 | 是否可能触发 |
|---|---|---|---|
| sanya-3d-allrain-outdoor-negative | 是 | 0/27 | 是（预期 PARTIAL） |
| lijiang-3d-allrain-history | 是 | 1/24 | 可能（allowed 已含 PARTIAL） |
| 其余 8 例 | 否 | - | 否 |

新增 L1 码：`weather_exposure_conflict`（v1 的 L0/L1 码表不变）。

## 3. 指标口径

沿用 v1：

- `effective_trials = 全部 trial - invalid_trial`；
- FDR / PDR / OMR 用 effective 分母；
- HPR / FPR 用 `plan_generated` 的有效 trial；
- MSR 在 v2 改称"用户点名必去命中率"，分子 = 全部 must_visit 出现在最终交付路线，分母 = 启用 must_visit 的有效 trial。

本轮 v2 只跑 3 个 must_visit 案例 × A/B/C × k=1 = **9 trial**，用于验证注入链路与 MSR，不用来替代 v1 的 30 条主消融。

## 4. invalid 判定

沿用 v1：

- `mode_effective ≠ mode_requested`；
- C 组 `nodes_entered` 不含 `time_check`；
- 首版快照缺失 / fixture 校验失败；
- Harness 异常。

429 / 账户限流仍归 `infra`，不计入 invalid，按 60/120/180s 退避。

## 5. 运行协议

```powershell
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v2 `
  --case nanjing-3d-sunny-history --case shanghai-1d-sunny-nightlife --case lijiang-5d-sunny-slowpace `
  --allow-external-calls --skip-existing `
  --out evaluation/trials/run-20261107-v2
```

限流环境保持单进程；不做并发分片。

## 6. 不做的事

- 不重新定义 v1 的 10 例与 66 trial；
- 不用 v2 的 9 trial 宣称整体成功率或稳定性；
- 不把 `weather_exposure_conflict` 回填进 v1 结果；
- 不为"让数字好看"调整 allowed_outcomes（南京标签修正是基于路线复核，不是结果调参）。
