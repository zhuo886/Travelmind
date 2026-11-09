# Travelmind 评测复盘 v1（2026-11-06）

> 对应口径：[EVAL_SPEC_V1.md](./EVAL_SPEC_V1.md)
> 对应结果：[EVAL_RESULTS_V1.md](./EVAL_RESULTS_V1.md)
> 原始数据：`evaluation/trials/run-20261106/`

## 1. 一句话结论

冻结口径下的 66 次真实运行证明：**审核闭环（Reviewer）是主要收益来源**（预期匹配率 36.4%→68.2%、硬约束 90.9%→100%、软质量 +7.3），代价是 Token ×3.9、延迟 ×3.8；**Time Check 是边际优化**；**最大产品缺口是"该拒绝时不拒绝"**，而不是稳定性。

## 2. 执行概况

| 项 | 值 |
|---|---|
| 实际耗时 | 约 3 小时 55 分（14:47 启动 → 18:42 完成，含 429 事故与串行重跑） |
| trial 总数 | 66（S1 9 + S2 30 + S3 27） |
| 无效 trial | 0 |
| 外部故障 | 最终入库 0；另有 16 次并发 429 尝试剔除后串行重跑（见 `INCIDENTS.md`） |
| LLM 调用 | 215 次 |
| Token（估算） | 输入 471,799 / 输出 141,556 |
| 模型 | glm-4.5-flash，temperature=0 |
| 失败重跑 | 3 并发触发 429，16 条脏记录删除后串行重跑 |

## 3. 结果回顾

### 3.1 总体

| 指标 | 值 |
|---|---|
| FDR 完整交付率 | 81.8%（54/66） |
| PDR 部分交付率 | 15.2%（10/66） |
| OMR 预期匹配率 | 57.6%（38/66） |
| HPR 硬约束通过率 | **97.0%**（64/66） |
| FPR 首轮通过率 | 90.9%（60/66） |
| MSR 指定景点命中率 | 80.0%（24/30） |
| RRR 返工修复率 | **100%**（4/4） |
| OOR 池外实体率 | **0.49%**（2/405） |
| 软质量均分 | 83.07 |

### 3.2 A/B/C（各 22 次）

| 指标 | A | B | C |
|---|---|---|---|
| HPR | 90.9% | 100% | 100% |
| OMR | 36.4% | 68.2% | 68.2% |
| 软质量 | 77.19 | 84.50 | 87.53 |
| 中位耗时 | 66.5s | 256.1s | 294.2s |
| 输入 Token | 2,454 | 9,567 | 9,425 |

### 3.3 稳定性（S3，成功型案例）

| 案例 | A | B | C |
|---|---|---|---|
| 南京 3 天 | pass@3 是 / pass^3 否 | 是 / 是 | 是 / 是 |
| 上海 1 天 | 否 / 否 | 是 / 是 | 是 / 是 |

## 4. 关键发现（按证据）

1. **两例硬失败全部来自 A 组，且都是 `unknown_poi`**
   - `sanya-3d-allrain-outdoor-negative / planner_only`
   - `shanghai-1d-sunny-nightlife / planner_only`
   - B/C 组硬失败为 0：Reviewer 能发现候选池外景点并强制返工。

2. **返工修复率 4/4 只在 B/C 成立**
   - 首版 L0 非空的 6 条中，A 组 2 条没有返工机制（`planning_revision_rounds=0`），不在 RRR 分母；
   - B/C 的 4 条全部修复成功（三亚 B×2、三亚 C×1、上海 B×1）。
   - 说明审核的价值不只是"打分"，而是**可执行的返工闭包**。

3. **Time Check 的边际收益很小**
   - 软质量 +3.03、OMR 不变、Token 基本不增（9,567→9,425）、延迟 +38s；
   - 它更像"兜底修正"，不是主收益来源。

4. **负样本是最大产品缺口**
   - `nanjing-3d-tighthours-negative` 在 B/C 组被判 `WRONG_ACCEPT`（应 `PARTIAL`/`CORRECT_REJECT`）；
   - `sanya-3d-allrain-outdoor-negative` 在 S3 的 9 次里全部 `MISMATCH`；
   - 系统倾向于"交付一份带 warning 的完整行程"，而不是明确拒绝不可行需求。

5. **MSR 的 6 次未命中全部集中在南京 3 天**
   - 因为 `must_visit=["玄武湖景区"]` 只是 benchmark 元数据，**没有写进 fixture query**；
   - 所以该指标应叫"benchmark 指定景点命中率"，不能当作"用户点名必去满足率"。

6. **耗时波动来自模型，不是编排**
   - planner 中位 85.3s、最大 313.1s；reviewer 中位 100.6s、最大 303.9s；
   - snapshot 节点中位 1.5–2.6ms，证明快照本身不影响性能。

## 5. 过程复盘

### 做得好的

- 判定逻辑复用生产 `hard_constraint_report` / `choose_snapshot`，评测与产品不分叉。
- `invalid_trial` 独立分母，避免把 harness 问题算成 Agent 失败。
- S1 DoD 门禁：模式不一致或 C 组未执行 time_check 就中止，未浪费 S2/S3 额度。
- `--skip-existing` 断点续跑，两次重启没有重复烧已完成 trial。
- 报告同时给出分子/分母/样本数，并把 "Pass@K 池化" 与 "S3-only" 分开说明。

### 失误与代价

1. **3 并发直接触发账户级 429**，产生 16 条 6 秒即失败的脏记录，删除后重跑，损失约 20–30 分钟与部分额度。
   - 教训：在未知限额下先做 2 并发探测；429 必须在 trial 级退避，不能只依赖内层 3 次快速重试。
2. **两次人工停止丢掉了在飞 trial**（每次约 5–10 分钟）。
   - 教训：长任务不要"看到慢就重启"，先确认进程与产物再决策。
3. **S1 与 S2 用例重叠**：S1 的 3 个案例在 S2 又跑了一遍（9 次重复），这是为了保证 S2 是完整 10 例矩阵，属于可接受但可优化。
4. **总报告的 Pass@K 使用池化 k（3–15）**，不能直接当 pass@3；已在结果文档中改用 S3-only。
5. **`must_visit` 未注入 query**：指标定义上留下了"不是用户真实约束"的解释成本。

## 6. 下一版改进清单

### P0（影响结论有效性）

1. **把 `must_visit` 写进对应 fixture 的 query**（如"想去玄武湖景区"），让生产 `active_must_visit` 真正生效，再重跑 3 例；否则 MSR 只能叫"指定景点命中率"。
2. **为负样本补"应当拒绝"的判据**：finalize 阶段对不可行请求输出明确的 `CORRECT_REJECT`（带 `physical_time_deadlock` / `candidate_pool_preference_conflict` 等原因），并把它纳入 allowed_outcomes。
3. **聚合器支持 per case×mode 的 Pass@K**，避免手工从 S3 目录计算。

### P1（提升证据强度）

4. 成功型案例扩到 k=5，并记录 pass@5 / pass^5。
5. 增加 3 例端到端切片（走 8766 SSE），单独报告端到端 P50/P95（fixture 结果不代表端到端）。
6. 固定 prompt 版本与模型版本字段，跨版本对比前先冻结。

### P2（成本/对照）

7. 对 A 组单独做"未知 POI 抑制"的 prompt 小实验，量化能否把 A 组 `unknown_poi` 从 2/22 降到 0。
8. 条件允许时做一次不同模型（deepseek / qwen）同口径对照，并明确标注不可直接横比。

## 7. 简历写法（基于本次实测）

可写：

- 10 例冻结评测集、66 次真实运行、0 无效；硬约束通过率 **97.0%**，池外实体 **2/405（0.49%）**。
- Planner→Reviewer 消融（每组 22 次）：OMR **36.4%→68.2%**、软质量 **77.2→84.5**、HPR **90.9%→100%**；代价 Token ×3.9、延迟 ×3.8。
- Time Check 边际：软质量 **87.5**，Token 基本不变。
- 成功型案例稳定性：A 组 pass@3 **50%**、pass^3 **0%**；B/C 组 pass@3 **100%**、pass^3 **100%**。
- 工程可靠性：215 次 LLM 调用、0 外部故障；限流按 60/120/180s 退避恢复。

不可写（会被追问）：

- "彻底解决景点幻觉"（实际 0.49% 仍有池外实体，且只在 A 组出现）。
- "多 Agent / Supervisor 协作"（本仓库是单图多角色）。
- "端到端成功率 x%"（fixture 模式不覆盖 intent 与候选补查）。
- 任何未经 k 次重复的"提升 x%"。

## 8. 复现命令

```powershell
# 0. 干跑确认用例与模式
python -m tests.eval.run_parallel --dry-run --workers 1

# 1. 完整矩阵（S1→S2→S3，真实调用；断点续跑）
python -m tests.eval.run_parallel --allow-external-calls --workers 1 `
  --out-root evaluation/trials/run-20261107

# 2. 单独重算指标（零成本）
python -m tests.eval.aggregate_trials `
  --dirs evaluation/trials/run-20261107/s1 evaluation/trials/run-20261107/s2 evaluation/trials/run-20261107/s3 `
  --out evaluation/trials/run-20261107/final
```

## 9. 产物索引

| 文件 | 内容 |
|---|---|
| `docs/EVAL_SPEC_V1.md` | 冻结口径（L0/L1、分母、allowed_outcomes、DoD） |
| `docs/EVAL_RESULTS_V1.md` | 结果表、诚实边界、简历句式 |
| `evaluation/trials/run-20261106/final/REPORT.md` | 最终报告（指标、A/B/C、按案例、节点耗时） |
| `evaluation/trials/run-20261106/final/summary.json` | 机器可读聚合结果 |
| `evaluation/trials/run-20261106/s1、s2、s3` | 66 条 trial 原始记录 |
