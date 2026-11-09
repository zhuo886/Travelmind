# v4 结果：Checkpoint 修改的输入预算与耗时拆解

> 脚本：`python -m tests.eval.modify_budget --out evaluation/benchmarks/modify_budget`
> 数据：`evaluation/benchmarks/modify_budget/summary.json`、`REPORT.md`
> 口径：`docs/EVAL_SPEC_V4.md` §1.2
> 本轮 0 次 LLM 调用：patch 掉 LLM 客户端，调用真实节点函数，捕获真实构造出的 prompt

## 1. 结论

| 指标 | 值 | 说明 |
|---|---:|---|
| A 臂入口 Token 均值 / 中位 | 3,346.8 / 3,215 | 全量重规划：intent + query_rewrite (+candidate_react) + planner |
| B 臂入口 Token 均值 / 中位 | 2,836.6 / 2,826 | checkpoint 修改：仅 planner，但 prompt 含上一版路线 |
| 变化 | **−15.2%** | 5 个 case 的均值差 |
| LLM 调用数中位 | **3 → 1** | A 臂含 intent 与 query_rewrite |
| 反向 case | **1 / 5** | lijiang 5 日游 +1.5% |

逐 case：

| case | A | B | 变化 |
|---|---:|---:|---:|
| lijiang-5d-sunny-slowpace | 3,215 | 3,263 | **+1.5%** |
| nanjing-3d-sunny-history | 2,957 | 2,757 | −6.8% |
| shanghai-1d-sunny-nightlife | 3,219 | 2,826 | −12.2% |
| nanjing-3d-tighthours-negative | 2,866 | 1,988 | −30.6% |
| sanya-3d-allrain-outdoor-negative | 4,477 | 3,349 | −25.2% |

天数越多、路线越长，B 臂 planner prompt 越大，越可能吃掉省下的 intent/query_rewrite。

## 2. 耗时拆解（只覆盖已测节点）

仓库里只有 planner / reviewer / time_check 三类节点有实测耗时，检索、餐食、贴士、
finalize 都没有。因此：

| 阶段 | 节点数 | 已测 | 估算耗时 | 占已测总量 |
|---|---:|---:|---:|---:|
| intake | 3 | 0 | 0ms | **N/A** |
| retrieval | 5 | 0 | 0ms | **N/A** |
| planning | 2 | 1 | 93,695.8ms | 37.3% |
| review | 3 | 2 | 157,725.8ms | 62.7% |
| finishing | 3 | 0 | 0ms | **N/A** |

- A 臂已测覆盖率 **18.8%（3/16 节点）**，B 臂 **37.5%（3/8 节点）**。
- 两臂的已测节点完全相同（planner/reviewer/time_check），**不能**由这张表推出耗时降幅。
- 全链路 P50 记为 `not_measured`。

## 3. 与 27 组真实配对的关系

| 项 | 值 | 性质 |
|---|---:|---|
| 重规划 P50 降幅 | +11.7%（剔除重试 −0.4%） | 27 组真实配对，同子图 |
| 输入 Token 降幅 | −6.6%（即增加 6.6%） | 同上 |
| 未修改内容保留率 | 73.5% → 90.6% | 同上 |
| 入口输入预算降幅 | −15.2% | 本轮 5 例 prompt 精算 |

**两组数字不能混算**：真实配对两臂都从 `planner` 起跑，检索阶段没进分母；
本轮精算只覆盖入口 prompt，不含检索节点耗时。

## 4. 可写与不可写

- 可写：`修改入口 LLM 调用 3 → 1，入口输入预算 −15.2%（5 例，1 例反向）`。
- 可写：`27 组真实配对：未修改内容保留率 73.5% → 90.6%`。
- 不可写：`重规划 P50 降低 31.8%`——本轮无检索阶段耗时，真实配对也只有不显著的 −0.4%。
- 不可写：把 −15.2% 说成"全链路预算"或"账单节省"。

## 5. 复现

```powershell
..\.venv\Scripts\python.exe -m tests.eval.modify_budget --out evaluation/benchmarks/modify_budget
```
