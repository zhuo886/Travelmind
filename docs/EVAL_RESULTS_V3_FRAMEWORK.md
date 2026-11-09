# 评测 v3 框架验证结果（2026-11-08）

> 框架验证阶段没有执行真实 planner / reviewer / judge 调用；真实 Judge、Reviewer 挑战与安全 trial 已单独执行，见 `docs/EVAL_RESULTS_V3_JUDGE.md`、`docs/EVAL_RESULTS_V3_REVIEWER.md`、`docs/EVAL_RESULTS_V3_SAFETY.md`、`docs/EVAL_RESULTS_V3_SAFETY_HARDREJECT.md`。
> 口径：`docs/EVAL_SPEC_V3.md`；Reviewer 基线：`docs/EVAL_REVIEWER_RELIABILITY.md`。
> 产物：`evaluation/reports/v3-baseline/`、`evaluation/reports/v3-reviewer/`、`evaluation/judge/run-20261108/`、`evaluation/reviewer_challenge/run-20261108/`、`evaluation/trials/run-20261108-safety/`（修复前）、`evaluation/trials/run-20261107-safety-hardreject-v2/`（修复后）。

## 1. 一句话结论

v3 框架已就绪：v1/v2 资产冻结校验通过，v3 能加载 12 个 case（含 2 个下界证明不可行的安全负样本），Judge 与 Reviewer 可靠性都有可运行的离线管线；全量测试 **134 passed**。真实 Judge 已跑 15 条 / 30 次调用（总分均值 78.73，pooled kappa 0.5975）；真实 Reviewer 挑战 6×2 完成（缺陷检出 10/10、正常对照误打回 0/2，但正常对照 2/2 带错误提醒）；真实安全 trial 6 条完成（硬拒绝修复后 **6/6 CORRECT_REJECT**，SRR 6/6、WAR 0/6、PARTIAL 0/6）。

## 2. 验证清单

| 项 | 结果 | 证据 |
|---|---|---|
| 全量测试 | **134 passed**（基线 92 + 新增 42） | `pytest -q tests` |
| v1/v2 冻结 | 指纹无变化 | `assets.frozen_mismatches() == []` |
| v3 资产 | 12 case，10 继承 v2 + 2 新增 | `run_trials --version v3 --dry-run` |
| v3 计划运行 | 12 案例 × 3 模式 = 36 trial | dry-run 输出 |
| 安全负样本 | 2/2 `INFEASIBLE`，现有 10 例无 `INFEASIBLE` 误判 | `feasibility.assess_version("v3")` |
| 上海时限证明 | 游览 180 + 直线通勤下界 92.882 = 272.9 分钟 > 120 分钟 | `feasibility` evidence |
| 三亚室内池证明 | `indoor_true=0`，`candidate_pool_preference_conflict` | `feasibility` evidence |
| v3 交付语义 | 草稿存在但 FAILED → `plan_generated=false`、`CORRECT_REJECT` | `tests/test_eval_safety.py` |
| Reviewer proxy 基线 | 81 条旧记录可计算，clean_block/regression 为 N/A | `evaluation/reports/v3-reviewer/REPORT.md` |
| Reviewer 挑战集 | 真实 6×2：缺陷 10/10 检出、正常对照 0/2 误打回、2/2 带错误提醒 | `docs/EVAL_RESULTS_V3_REVIEWER.md` |
| 真实安全 trial | 硬拒绝后 6/6 CORRECT_REJECT；SRR 6/6、WAR 0/6、PARTIAL 0/6 | `docs/EVAL_RESULTS_V3_SAFETY_HARDREJECT.md` |
| Judge 管线 | v2 9 条 trial 可评分；stub 确定性、双评、缓存、预算、盲评均通过测试 | `evaluation/judge/selftest/` |
| 真实 Judge | 15/15 有效、30 次调用、0 错误；总分 78.73、pooled kappa 0.5975 | `docs/EVAL_RESULTS_V3_JUDGE.md` |
| 真实调用 | Judge 30 次 + Reviewer 12 次 + 安全 6 trial | 对应 run 目录 |

## 3. 零成本基线（旧记录，不是 v3 结果）

`evaluation/reports/v3-baseline/REPORT.md` 合并 81 条旧 trial：

| 指标 | 值 |
|---|---|
| FDR / PDR / OMR | 81.5% / 14.8% / 56.8% |
| HPR / FPR | 96.3% / 88.9% |
| MSR | 33/39 = 84.6% |
| 分母口径 | `plan_generated`（旧口径） |
| Safety / Judge / Expectations | N/A（旧记录没有标签或 Judge 结果） |

该报告只用于验证聚合器与新版表格，不替代 v1/v2 的既有结论。

## 4. Judge 自测说明

`evaluation/judge/selftest/` 使用 `--provider stub` 对 v2 的 9 条 trial 跑通管线：

- 9/9 有 `route_by_day`，可构造盲评 payload；
- 双评 kappa、缓存、预算、schema 校验均有测试覆盖；
- **stub 分数全部为 81.5，只是确定性假评分，不能当质量结果**。
- `evaluation/judge/selftest_checkpoint/` 另验证了 54 条 checkpoint A/B 的 `route` 适配器；同样是 stub，不可当结果。

现有 66 条 v1 trial 没有 `route_by_day`，Judge 覆盖率为 0；主消融需要下一轮重跑或另找路线来源。

真实 Judge 结果（rubric v2 / prompt v2）：15 条、30 次调用、37,126 Token、0 错误，总分均值 **78.73**，pooled kappa **0.5975**；最低是 Sanya 全雨全露天 53.0。详见 `docs/EVAL_RESULTS_V3_JUDGE.md`。

## 5. Reviewer 挑战集

真实运行（`glm-4.5-flash`，k=2，12 次调用、32,488 Token、median 51.6s、0 错误）：

- 5 类注入缺陷 10/10 检出，关键词 10/10 命中；
- clean control 0/2 误打回；
- 但 clean control 2/2 出现**错误的开放时间提醒**（日期/星期推理错误，且违反“不要评审开放时间”的 prompt）。

因此“误打回 0%”只代表 verdict，不代表提醒质量。5 类缺陷偏显眼，不能外推为语义审核准确率 100%。详见 `docs/EVAL_RESULTS_V3_REVIEWER.md`。

## 6. 安全负样本

硬拒绝修复后（2 案例 × A/B/C = 6 trial，0 invalid，6/6 MATCH）：

- 三亚室内池冲突：3/3 `CORRECT_REJECT`，无草稿；B/C 从 276.8/292.1s 降到 58.9/67.2s。
- 上海 2 小时 + 3 必去：A/B/C 全部 `CORRECT_REJECT`；B 161.1s、C 203.6s，不再交付 PARTIAL。
- SRR **6/6**，WAR **0/6**，不安全交付 0/6，PARTIAL **0/6**。
- Reviewer trace：快照 18 → 8，返工事件 12 → 2。

修复前基线（4 拒绝 + 2 PARTIAL）见 `docs/EVAL_RESULTS_V3_SAFETY.md`；修复后见 `docs/EVAL_RESULTS_V3_SAFETY_HARDREJECT.md`。

## 7. 尚未验证 / 明确 N/A

- 真实 Judge 与人工校准的一致性（当前没有人工标签，MAE/Spearman 为 N/A）；
- 更大样本的 Reviewer 误打回、自然失败检测与 issue precision（当前 clean 只有 1 例）；
- 更大样本的安全 SRR/WAR/PARTIAL（当前 2 案例 × 3 模式）；
- v3 `delivered_plan` 语义下的完整 A/B/C 消融；
- E3 四臂与 E4 门控回放。

## 8. 复现命令

```powershell
# 真实 Judge：15 条已有 route 的 trial（已执行）
..\.venv\Scripts\python.exe -m tests.eval.judge --trials evaluation/trials/run-20261107-v2 --trials evaluation/trials/run-20261107-negative --version v2 --provider llm --k 2 --max-calls 40 --allow-external-calls --out evaluation/judge/run-20261108

# 真实 Reviewer 挑战：6 × k=2（已执行）
..\.venv\Scripts\python.exe -m tests.eval.reviewer_challenge --allow-external-calls --k 2 --out evaluation/reviewer_challenge/run-20261108

# 仅重算 Reviewer 报告（不发请求）
..\.venv\Scripts\python.exe -m tests.eval.reviewer_challenge --replay-summary evaluation/reviewer_challenge/run-20261108/summary.json --out evaluation/reviewer_challenge/run-20261108

# v3 安全负样本：2 案例 × 3 模式 = 6 trial（硬拒绝修复后，已执行）
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 --case shanghai-1d-twohour-three-must-negative --case sanya-1d-indooronly-empty-pool-negative --allow-external-calls --out evaluation/trials/run-20261107-safety-hardreject-v2
```

## 9. 边界

- 不把 stub 分数写进任何结论。
- 不把 81 条旧记录的 proxy 结果与 v3 `delivered_plan` 结果混算。
- 不写“系统会硬拒绝所有不可行请求”：当前只对 `physical_time_deadlock` 与 `candidate_pool_preference_conflict` 硬拒绝；其他 L1 仍可能 PARTIAL。
- 不写“安全拒绝率 100%”：当前 SRR 6/6 只来自 2 个已知不可行案例，不是整体安全率。
- 不写“WAR 0% 所以安全”：PARTIAL 仍可能交付不可行时间表；硬拒绝修复后当前 partial=0。
- 不写“Reviewer 误打回率 0%”：clean 只有 2 次，且 2/2 带错误提醒。
- 不写“Reviewer 语义审核准确率 100%”：5 类注入缺陷偏显眼，不能外推到自然失败。