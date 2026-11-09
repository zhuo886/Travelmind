# v1 负样本复核：南京紧时段 / 三亚全雨

> 复核日期：2026-11-06 19:25–19:48。模型 `glm-4.5-flash`（temperature=0），k=1，单进程串行。
> 数据：`evaluation/trials/run-20261107-negative/`（6 条 trial，全部 `invalid_trial=false`）。
> 本文件只记录复核结论，不修改 `EVAL_SPEC_V1.md` / `EVAL_RESULTS_V1.md` / v1 原始 trial。

## 0. 为什么需要复核

v1 的 66 次运行里，两个"负样本"在 S2 与 S3 中全部得到 `SUCCESS_WITH_WARNINGS`：

- `nanjing-3d-tighthours-negative`：期望 `[PARTIAL, CORRECT_REJECT]`，实际 `SUCCESS_WITH_WARNINGS` → `MISMATCH` / `WRONG_ACCEPT`
- `sanya-3d-allrain-outdoor-negative`：期望 `[PARTIAL, CORRECT_REJECT]`，实际三组均为 `SUCCESS_WITH_WARNINGS` → `MISMATCH`

v1 trial 记录当时只保存失败码，没有保存最终路线，无法离线判断"到底是系统该拒绝而没拒绝，还是样本本身可行"。本次先给 `build_trial_record` 补 `route_names` / `route_by_day` / `warnings`，再重跑 2 案例 × 3 模式。

## 1. 结论摘要

| 案例 | 复核结论 | 处置 |
|---|---|---|
| 南京紧时段 | **fixture 标签错误**：6 个景点 / 3 天 / 每天 2 个，全部落在开放时间内，B/C 交付合法行程 | v2 把 `allowed_outcomes` 改为 `[SUCCESS, SUCCESS_WITH_WARNINGS]`；v1 原记录不改 |
| 三亚全雨 | **真实产品缺口**：路线 9 个景点全部 `indoor=false`，3 天均为中雨；Reviewer 已明确写出"雨天条件下完全不可行"，但最终 status 仍是 `SUCCESS_WITH_WARNINGS` | v2 新增确定性 L1 `weather_exposure_conflict`，把"全程恶劣天气 + 全室外"降级为 `PARTIAL_SUCCESS` |

## 2. 南京 `nanjing-3d-tighthours-negative`

### 2.1 输入事实

- 3 天（2026-08-25 ~ 2026-08-27），全晴，`max_per_day=3`
- 候选池 7 个景点，开放时间集中在 09:00–17:30（仅欢乐谷有季节区间）
- query 为"南京3天游（负样本：景点池以开放时间短的景点为主，考验时刻表合理性）"

### 2.2 实际交付路线

| 模式 | status | soft | L0 / L1 | 交付路线（每天） |
|---|---|---|---|---|
| A planner_only | SUCCESS_WITH_WARNINGS | 87 | 空 / 空 | D1 古鸡鸣寺、中山陵；D2 不老村、水墨大埝；D3 汤山博物馆、欢乐谷 |
| B planner_reviewer | **SUCCESS** | 97 | 空 / 空 | D1 不老村 10:00–12:30、水墨大埝 13:30–16:30；D2 中山陵 10:00–12:30、古鸡鸣寺 14:00–16:30；D3 汤山博物馆 10:00–12:30、欢乐谷 13:30–16:30 |
| C + time_check | **SUCCESS** | 100 | 空 / 空 | D1 古鸡鸣寺 10:00–12:00、中山陵 14:00–16:30；D2 汤山博物馆 10:00–12:00、欢乐谷 14:00–17:00；D3 不老村 10:00–12:00、水墨大埝 14:00–16:00 |

### 2.3 判定

- 6 个路线景点均在候选池内（`oor = 0/6`）；
- 每个景点的 `start/end` 都落在各自开放区间内；
- 3 天行程、每天 2 个景点，未超过 `max_per_day=3`；
- 没有任何 L0/L1 违规。

**因此该样本在冻结输入下是可执行的，系统返回 SUCCESS 是正确行为。**
`allowed_outcomes=[PARTIAL, CORRECT_REJECT]` 与 fixture 内容不一致，是 benchmark 标签问题，不是 Agent 能力问题。

### 2.4 处置

- v1 记录与 spec 保持原样；
- `benchmark_v2.json` 中该案例改为 `[SUCCESS, SUCCESS_WITH_WARNINGS]`；
- 真正不可行的负样本另建（P1，例如 1 天 2 小时窗口 + 3 个必去），本轮不新增。

## 3. 三亚 `sanya-3d-allrain-outdoor-negative`

### 3.1 输入事实

- 3 天（2026-10-15 ~ 2026-10-17），三天均为**中雨**（`is_bad=true`）
- 候选池 27 个景点，`indoor` 全部为 `false`（海滩/湾区/公园）
- `rain_indoor_priority=false`，`expectations.outdoor_on_bad_day_max=1`

### 3.2 实际交付路线

| 模式 | status | soft | L0 / L1 | 交付路线要点 |
|---|---|---|---|---|
| A planner_only | **PARTIAL**（MATCH） | 57 | 空 / `opening_time_conflict` | 9 个全室外；D3 蜈支洲岛排在 16:30–18:30，但 16:30 停止入园 |
| B planner_reviewer | SUCCESS_WITH_WARNINGS（MISMATCH） | 67 | 空 / 空 | 9 个全室外（天涯小镇、天涯海角、崖州古城、椰梦长廊、三亚湾、海月广场、后海村、亚龙湾海滩、海棠河生态公园） |
| C + time_check | SUCCESS_WITH_WARNINGS（MISMATCH） | 57 | 空 / 空 | 9 个全室外（南山大小洞天、南山景区、海上观音、天涯海角、天涯小镇、三亚湾、亚龙湾海滩、亚龙湾度假区、天下第一湾） |

B 组 Reviewer 原文（节选）：

> "严重违反天气合理性约束：全程3天均为中雨天气，但所有安排的景点均为明确室外海滨景点。必须重新规划……当前路线在雨天条件下完全不可行。"

C 组 Reviewer 原文（节选）：

> "天气合理性严重不达标：三天均为中雨天气，但所有安排的9个景点均为明确室外景点……"

### 3.3 判定

- 两天/三天全室外，与 `outdoor_on_bad_day_max=1` 明显冲突；
- Reviewer 已经识别出问题，但 `choose_snapshot` 只按 L0/L1 分层选快照，Reviewer 的文字结论只进入 `warnings`，不会把 `SUCCESS_WITH_WARNINGS` 降级为 `PARTIAL_SUCCESS`；
- A 组的 PARTIAL 是 `opening_time_conflict` 撞出来的，**与天气无关**，属于偶然 MATCH。

**因此这不是"模型没看出来"，而是"看出来了但没有结构化降级"。**

### 3.4 处置

v2 在生产代码中新增确定性规则 `weather_exposure_conflict`（L1）：

- 触发条件：`weather_forecast` 非空、**所有**旅行日 `is_bad=true`、路线非空、**所有已排景点** `indoor=false`；
- 效果：`choose_snapshot` 落入 tier2 → `PARTIAL_SUCCESS`，并保留具体提醒；
- 作用域：只覆盖"全程雨 + 全室外"，不影响"单日雨但当天有室内"的南京单雨案例。

## 4. 复核中发现的附加问题（P2，本轮不修）

1. **开放时间季节区间未生效**：南京 C 组把「南京欢乐谷」排在 2026-08-26，而该 POI 的 `open_time` 从 8 月 31 日起才有区间；当前解析没有把它判为闭馆/未知，属于 `opening_time` 解析的覆盖缺口。
2. **fixture `expectations` 未进入判定**：`outdoor_on_bad_day_max` 写在 fixture 里，但 `tests/eval/metrics.py` 从未读取；三亚的"负样本语义"没有可执行的判定入口。
3. **planner_only 的 warning 文案**：A 组出现了"审核提出的软性体验建议已作为提醒保留"，但 A 组没有 Reviewer；来源是 `choose_snapshot` 对 `reviewer_approved` 默认值的兜底，属文案层面问题。

## 5. 复现

```powershell
..\.venv\Scripts\python.exe -m tests.eval.run_trials `
  --case nanjing-3d-tighthours-negative --case sanya-3d-allrain-outdoor-negative `
  --allow-external-calls --out evaluation/trials/run-20261107-negative
```

> 该命令会真实调用 LLM；限流环境请串行执行（`run_parallel --workers 1`）。本次 6 条 trial 无 429，无 invalid。
