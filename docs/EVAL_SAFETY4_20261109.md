# 安全负样本扩到 4 类机理 + 雨天 L1 验证（2026-11-09）

> 产物：`evaluation/trials/run-20261109-safety4/`（12 trial）、`evaluation/trials/run-20261109-weather-l1/`（6 trial）
> 配置：`glm-4.5-flash`、思考链全关、`LLM_CALL_TIMEOUT_SECONDS=240`
> 本轮同时验证三处改动：① LLM 墙钟上限 ② 雨天室外 L1 ③ 两类新不可行机理

## 1. 安全 4 类机理：3 类守住，1 类失守

| 机理 | 案例 | A | B | C | 结论 |
|---|---|---|---|---|---|
| `candidate_pool_preference_conflict` | sanya 室内空池 | CORRECT_REJECT | CORRECT_REJECT | CORRECT_REJECT | ✅ 3/3 |
| `physical_time_deadlock` | shanghai 2 小时 3 必去 | CORRECT_REJECT | CORRECT_REJECT | CORRECT_REJECT | ✅ 3/3 |
| `required_poi_unavailable`（新） | shanghai 点名"上海天文馆" | CORRECT_REJECT | CORRECT_REJECT | CORRECT_REJECT | ✅ 3/3 |
| `opening_hours_deadlock`（新） | nanjing 20:00–22:00 逛闭馆景点 | PARTIAL（MATCH） | **SUCCESS（WRONG_ACCEPT）** | **SUCCESS（WRONG_ACCEPT）** | ❌ 0/3 |

汇总：SRR **9/12 = 75%**、WAR **2/12 = 16.7%**、PARTIAL 1/12；
修复前（只有 2 类）是 SRR 6/6，扩样后**立刻暴露第三类没守住**。

### 1.1 失守的细节

`nanjing-1d-night-closed-negative`（20:00–22:00，池内 5 个景点最晚 17:30 闭馆）：

- A 臂：`PARTIAL_SUCCESS` + L1 `opening_time_conflict` → 交付了一份"闭馆时段去逛"的行程；
- B / C 臂：**`SUCCESS` + `WRONG_ACCEPT`**，L0/L1 全空 —— 审核把 L1 冲突"修掉"了，
  但它修的是排期时间，不是"景点根本不开放"这个事实；
- 对照：`shanghai-1d-unavailable-poi-negative` 三臂全部正确拒绝（`unknown_poi` / `missing_must_visit`）。

**根因**：`opening_time_conflict` 只是 L1（可修复项），而"整段时间窗内池内景点全闭馆"是
**不可修复**的物理事实，应走硬拒绝。判断依据在 `tests/eval/feasibility.py` 已实现
（`opening_hours_deadlock`），但产品侧没有对应判定。

**建议修法**：在 `hard_constraint_report` 增加"窗口 × 全池营业时间"的判定，命中即 L0
（或直接 `FAILED`），与 `candidate_pool_preference_conflict` 同级；不要依赖 Reviewer 语义判断。

## 2. 雨天室外 L1：触发了，但没有改变结果

`sanya-3d-allrain-outdoor-negative`（全程中雨 + 偏室外）与 `lijiang-3d-allrain-history` 的复跑：

| 案例 / 臂 | L1 码 | expectation 违反次数 |
|---|---|---|
| sanya / B | `weather_exposure_conflict` + **`weather_outdoor_mismatch` ×3** | 3 |
| sanya / C | 同上 ×4 | 3 |
| lijiang / B | `duplicate_poi` ×2、`opening_time_conflict` | 3 |
| lijiang / C | **`weather_outdoor_mismatch` ×2**、`duplicate_poi` ×2 | 3 |
| nanjing-singlerain / B、C | 无（单日雨、室外点 <2） | 1 |

- **新 L1 确实被触发**，且经 `_planner_constraint_guard` 进入返工提示
  （`nodes.py:1148` 读上一轮 `l1_violations`）。
- **但 `outdoor_on_bad_day_max` 违反次数没有下降**：修改前 B 7 次 / C 5 次，修改后 B 7 次 / C 7 次。
- 解释：三亚 fixture 是"全雨 + 池内几乎全露天"，**客观上无室内替代**，L1 无法被消除；
  丽江案例则出现 B 未触发、C 触发，属路线差异而非修复。

结论：**把软约束变成 L1 只能"让它被看见"，不能"让它被修好"**。要真正生效需要两件事之一：
① 命中该 L1 时禁止交付完整成功（降级 PARTIAL）；② 或把它接入"候选重排"（强制换室内），
而不是只交给 planner 的语言反馈。

## 3. 本轮改动的工程验证

| 改动 | 验证 |
|---|---|
| LLM 墙钟上限（`LLM_CALL_TIMEOUT_SECONDS=240`） | 本轮 18 条 trial 无挂起；最长单条 238.7s（丽江 B），均在 240s 内；单元测试覆盖超时抛错与被重试 |
| 雨天室外 L1 | 已在 sanya/lijiang 真实触发；nanjing 单日雨未误触发 |
| 4 类不可行机理 | v3 14 案例中恰好 4 个 `INFEASIBLE`，`validate_version('v3') == []`，既有 12 案例无新增误判 |
| 回归 | `pytest -q tests` → **211 passed** |

## 4. 复现

```powershell
$env:OPENAI_THINKING="disabled"; $env:OPENAI_THINKING_PLANNER="disabled"
# 4 类负样本 × 3 臂
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --case nanjing-1d-night-closed-negative --case shanghai-1d-unavailable-poi-negative `
  --case sanya-1d-indooronly-empty-pool-negative --case shanghai-1d-twohour-three-must-negative `
  --allow-external-calls --out evaluation/trials/run-20261109-safety4
# 雨天 L1 验证
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --case sanya-3d-allrain-outdoor-negative --case lijiang-3d-allrain-history `
  --case nanjing-3d-singlerain-history --mode planner_reviewer --mode planner_reviewer_time_check `
  --allow-external-calls --out evaluation/trials/run-20261109-weather-l1
```

## 5. 边界

- n=12（每案例 3 臂）、n=6（天气验证），只能作机理证据，不能报"安全率 75%"。
- `nanjing-1d-night-closed-negative` 的营业时间来自冻结 fixture 的高德文本，真实营业时间会变；
  该案例证明的是"系统没有能力识别窗口内闭馆"，不是"某景点确实闭馆"。
- `required_poi_unavailable` 只在**冻结池语义**下不成立之外不可行；真实链路中系统本应通过
  高德检索补全，属评测边界，不能写成"系统不支持冷门景点"。
- 三亚全雨案例的 L1 残留是**池内无室内替代**导致，不能写成"Reviewer 修不好天气问题"。
- 期望规则 `outdoor_on_bad_day_max` 与新 L1 的统计口径不同（前者按行程汇总、后者按天计 ≥2），
  两个数字不可直接互证。
