# v4 结果：分层审核闭环（四臂回放）

> 脚本：`python -m tests.eval.production_policy --out evaluation/benchmarks/policy`
> 数据：`evaluation/benchmarks/policy/summary.json`、`REPORT.md`
> 口径：`docs/EVAL_SPEC_V4.md` §2、§3
> 性质：**回放**。A/B/C 取自已冻结 trial 的真实结果，D 臂把 A 首版路线喂给真实 `route_risk_gate_node`

## 1. 四臂指标（ESR 分母 5）

| 臂 | 来源 | trial | ESR | OMR | HPR | PDR | Token 合计 | P50 耗时 |
|---|---|---:|---|---|---|---|---:|---:|
| A planner_only | 真实 | 5 | 40.0%（2/5） | 40.0%（2/5） | 80.0%（4/5） | 40.0%（2/5） | 16,629 | 99.6s |
| B planner+reviewer | 真实 | 5 | 60.0%（3/5） | 60.0%（3/5） | **100%（5/5）** | 0.0%（0/5） | 62,283 | 249.6s |
| C +time_check | 真实 | 5 | 60.0%（3/5） | 60.0%（3/5） | 100%（5/5） | 0.0% | 50,235 | 236.3s |
| D 生产 risk gate | **回放** | 5 | 60.0%（3/5） | 60.0%（3/5） | 100%（5/5） | 0.0% | 50,235 | 236.3s |

- HPR 从 80% 提到 100%，代价是 Token **×3.02**、P50 **×2.37**。
- C 与 B 的 ESR/OMR 相同：Time Check 没有进一步提高可执行成功率，只把 PARTIAL 归零。
- D ≡ C：本批 5 个 case 全部需要审核（skip 0/5），门控没有产生分流。

## 2. 草稿级门控分流（30 份）

| 来源 | 草稿 | 被跳过 | 缺陷已知 |
|---|---:|---:|---:|
| trial（v2 9 + negative 6） | 15 | 0 | 15 |
| checkpoint（E2 配对 A 臂路线） | 15 | 0 | 0 |
| 合计 | **30** | **0** | 15 |

- 跳过率 **0 / 30**。
- checkpoint 草稿没有 `l0_codes`，误跳过只在 15 份"缺陷已知"草稿上有意义。

## 3. 增益归因：规则驱动 vs 语义驱动

| 项 | 次数 |
|---|---:|
| 返工 trial（`planning_revision_rounds > 0`） | 5 |
| 其中首版有 L0、返工后修好（规则驱动） | **2** |
| 其中首版有 L0、返工后仍在（规则无效） | 0 |
| 其中首版无 L0、仍发生返工（语义驱动） | 3 |

结论：**硬约束增益来自确定性规则门控 + 返工**（2/2 全部是 `unknown_poi` 被修掉），
不能把 HPR 80%→100% 归功于"语义审核能力"。另外 3 次返工发生在首版已无 L0 的情况下，
属于软约束层面的调整，未改变 ESR。

口径说明：没有使用 `snapshot_trace.rework_requested`——旧记录里它恒为 False
（shanghai B 返工 3 轮仍全为 False），用它归因会得出"没有返工"的错误结论。

## 4. 可写与不可写

- 可写：`四臂回放：HPR 80%(4/5) → 100%(5/5)、ESR 40%(2/5) → 60%(3/5)、PARTIAL 40% → 0%；代价 Token ×3.02、P50 ×2.37`。
- 可写：`5 次返工中 2 次由 L0 触发并修好、3 次语义驱动、0 次规则无效`。
- 不可写：`任务成功率 86.7% → 100%`（不是本仓库数据，n=5 也不能外推）。
- 不可写：`D 臂证明门控有效`（skip=0，D 与 C 完全相同）。
- 不可写：`Reviewer 语义审核带来提升`（归因显示增益来自规则）。

## 5. 复现

```powershell
..\.venv\Scripts\python.exe -m tests.eval.production_policy --out evaluation/benchmarks/policy
```
