# v4 结果：自适应审核跳过（30 份草稿回放）

> 脚本：`python -m tests.eval.adaptive_review --out evaluation/benchmarks/adaptive`
> 数据：`evaluation/benchmarks/adaptive/summary.json`、`REPORT.md`
> 口径：`docs/EVAL_SPEC_V4.md` §4
> 性质：**回放 + 策略对照**，0 次模型调用

## 1. 现状策略（`semantic_review=True`）

| 指标 | 值 |
|---|---:|
| 草稿 | 30（trial 15 + checkpoint 15） |
| 跳过审核 | **0 / 30（0.0%）** |
| 误跳过 | 0（分母 0 → 比率 **N/A**） |
| 反事实 Token 节省 | 0 |

原因：`route_risk_gate_node` 在 `semantic_review=True` 时，只要 query 含
`attraction_preference` / `habit_preference` / "喜欢\|希望\|不想" 就追加
`preference_review` 并强制 `review_required=True`。12 个 fixture 全部命中。

**结论：`自适应跳过低风险审核使 Token 减少 61.8%` 在当前实现下不可复现。**

## 2. 放宽策略（`semantic_review=False`，仅作对照）

| 指标 | 值 |
|---|---:|
| 跳过审核 | **19 / 30（63.3%）** |
| 误跳过 | 0 / 19（**0.0%**，缺陷已知 15 份） |
| 被跳过草稿的缺陷分布 | `{}`（0 个 L0/L1 缺陷；仅 15 份缺陷已知草稿可数） |
| 反事实 Token 节省 | 124,241（占可比审核 Token 57.5%） |
| 被跳过的草稿 | 19 份（trial 9 + checkpoint 10） |

误跳过 0 且缺陷分布为空，只代表“这 19 份草稿没有 L0 或不可交付 L1”，不代表语义质量没下降——
草稿的软约束问题（偏好不符、节奏过满）不在 L0/L1 里，这个实验看不见。

注意：
- 反事实节省按"同 case `planner_reviewer` 与 `planner_only` 的 Token 差"估算；
  同一 case 的多份草稿共用同一增量，因此合计值是上限，不是账单节省。
- 即使 63.3% 看起来接近原项目的 61.8%，两者不可等同：原数字是真实账单，
  本轮是回放反事实，且错误跳过率的分母只有 15 份草稿。

## 3. 修复方向（若要真正拿到收益）

1. 把 `preference_review` 从"无条件强制升级"改为按偏好文本强度分级
   （弱偏好如"随便逛逛"走确定性门控，强偏好如"必须去 X"才升级）。
2. 用本脚本回归：`skip_rate` 上升的同时，`false_skip_rate` 必须保持可接受。
3. 再用真实 trial 验证 ESR/HPR 没有下降（本轮做不到，见下）。

## 4. 可写与不可写

- 可写：`30 份真实草稿回放：现状门控跳过率 0%，因此不宣称 Token 收益`。
- 可写：`放宽为仅确定性门控后跳过 19/30，误跳过 0/19（缺陷已知 15 份）`——须同时给出分母。
- 不可写：`自适应跳过节省 Token 61.8%`。
- 不可写：`放宽策略安全`——软约束退化不在 L0/L1 里，本实验测不到。

## 5. 复现

```powershell
..\.venv\Scripts\python.exe -m tests.eval.adaptive_review --out evaluation/benchmarks/adaptive
```
