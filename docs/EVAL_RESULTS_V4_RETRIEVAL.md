# v4 结果：有界 ReAct 检索的合规、补查与幻觉阻断

> 脚本：`python -m tests.eval.candidate_budget`、`python -m tests.eval.gap_fill_ablation`
> 数据：`evaluation/benchmarks/{candidate_budget,gap_fill}/summary.json`
> 口径：`docs/EVAL_SPEC_V4.md` §1.3、§1.4
> 本轮 0 次真实检索调用：trial 聚合只读落盘字段；补查消融用桩化检索

## 1. 预算：81 条 trial 无法证明，改由 28 场景证明

| 证据来源 | 结论 |
|---|---|
| 81 条冻结 trial | `candidate_api_calls` **恒为 0**（harness 从 planner 起跑，不经过检索节点）→ trial 口径 **N/A**，不是 100% |
| 28 个受控场景（bounded_react 臂） | 预算合规 **28/28（100%）**；单场景检索次数最大 **2**（上限 10）；轮次 ≤ 2 |

两个口径分开报：trial 从未触及检索，把 0 次调用算成 100% 是空转指标；
真正跑过真实决策队列与执行器的是受控场景，那 28/28 才有意义。

## 2. 补查效果（28 场景消融）

| 臂 | 场景 | 缺口 | 修复 | 新增缺口 |
|---|---:|---:|---:|---:|
| seed_only（无补查） | 21 | 35 | **0** | 0 |
| bounded_react（真实决策+执行器） | 21 | 35 | **28** | 0 |
| boundary（池与检索源都没有） | 7 | 14 | **0** | 0 |

- 修复率 **28/35（80.0%）**；未补齐的 7 个全部是 named 场景里的 `count` 缺口（场景只提供了点名点，属设计边界）。
- 边界场景 **0/14** 被错误补齐 → 没有凭空造点。
- 每种缺陷各 7 个场景：`named` / `indoor` / `count` / `boundary`。

## 3. 幻觉阻断（三层证据）

| 层级 | 指标 | 值 |
|---|---|---:|
| 引用级 | 池外景点引用 / 总引用 | **3 / 505（0.59%）** |
| trial 级 | 含 `unknown_poi` 的 L0 | 9 条（全部在 `planner_only`） |
| 拦截级 | 首版有 `unknown_poi`、交付已修掉 | **6 条** |

分模式：

| 模式 | trial | `unknown_poi` L0 |
|---|---:|---:|
| planner_only | 27 | **3** |
| planner_reviewer | 27 | 0 |
| planner_reviewer_time_check | 27 | 0 |

说明：`first_draft_unknown_poi` 为 9，最终只剩 3（A 臂），差额 6 就是 Reviewer 修掉的部分。

## 4. 点名必去与去重

分批统计（v2 的 9/9 不能被 v1 稀释）：

| 数据桶 | 参与 | 通过 | 覆盖率 | 未通过 trial |
|---|---:|---:|---:|---|
| v1（`run-20261106`） | 30 | 24 | **80.0%** | nanjing-3d-sunny-history 的 6 条 |
| v2（`run-20261107-v2`） | 9 | 9 | **100%** | — |
| 合计 | 39 | 33 | 84.6% | — |

v1 的 6 条失败全部是 `nanjing-3d-sunny-history`（必去“玄武湖景区”未排入），属真实缺口，不是口径问题。

### v3 安全样本（单列，不进可行集分母）

| 项 | 值 |
|---|---:|
| trial | 6（6/6 `CORRECT_REJECT`） |
| `must_visit` 参与 / 通过 | 3 / 0 |

这 3 条的 `must_visit_ok=False` 是“正确拒绝、未交付路线”的结果，与 `CORRECT_REJECT` 一致，
不应当作覆盖失败——这也是必须把安全样本单列的原因。

- 去重与缓存命中：**N/A**。旧 trial 没有落盘 `candidate_search_trace`，本轮起
  `run_trials` 补写该字段（含 `error_code` / `cache_hit` / `result_count`），下一轮才有数据。

## 5. 可写与不可写

- 可写：`28 个受控场景补齐 28/35 个非边界缺口；仅种子池 0/35；边界 0/14 误补`。
- 可写：`池外引用 3/505（0.59%）；首版 unknown_poi 被 Reviewer 修掉 6 条`。
- 可写：`v2 点名必去 9/9；v1 24/30；v3 安全样本单列 6/6 CORRECT_REJECT`。
- 不可写：`预算合规 100%` 而不给口径（必须标明来自 28 个受控场景，不是 81 条 trial）。
- 不可写：把 28/35 说成"路线成功率"；桩化检索固定了召回。
- 不可写：`去重 + 缓存命中 X`（数据不存在）。

## 6. 复现

```powershell
..\.venv\Scripts\python.exe -m tests.eval.candidate_budget --out evaluation/benchmarks/candidate_budget
..\.venv\Scripts\python.exe -m tests.eval.gap_fill_ablation --out evaluation/benchmarks/gap_fill
```
