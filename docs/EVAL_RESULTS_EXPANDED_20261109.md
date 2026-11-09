# 扩样结果：12 案例 × 3 臂 = 36 trial（2026-11-09）

> 目录：`evaluation/trials/run-20261109-expanded/`（`REPORT.md` / `summary.json` / 36 份 trial）
> 资产：`tests/eval` v3（12 案例，含 3 个下界可证不可行的负样本）
> 配置：`glm-4.5-flash`、`OPENAI_THINKING=disabled`、`OPENAI_THINKING_PLANNER=disabled`、`max_tokens=8000`、`json_mode`
> 全部真实调用，0 invalid、0 超时丢弃（一条 2 小时挂起样本单独说明，见 §6）

## 1. 总体（n=36）

| 指标 | 分子/分母 | 值 |
|---|---|---:|
| 完整交付率 FDR | 21 / 36 | 58.3% |
| 部分交付率 PDR | 8 / 36 | 22.2% |
| 预期结果匹配率 OMR | 32 / 36 | **88.9%** |
| 硬约束通过率 HPR | 29 / 29 | **100%** |
| 首轮通过率 FPR | 27 / 29 | 93.1% |
| 必去满足率 MSR | 8 / 12 | 66.7%（见 §5 分母说明） |
| 返工修复率 RRR | 2 / 2 | 100% |
| 池外实体率 OOR | 0 / 180 | **0%** |
| 软质量分 | n=29 | 86.18 |
| 端到端 median / P95 | n=36 | 68.5s / 183.5s |
| 结果分布 | — | SUCCESS_WITH_WARNINGS 12、SUCCESS 9、PARTIAL 8、CORRECT_REJECT 6、FAILED 1 |
| 标签分布 | — | MATCH 32、MISMATCH 3、OVER_REJECT 1 |

安全侧（仅不可行样本）：**SRR 6/6 = 100%**、WAR 0/6、不安全交付 0/6、PARTIAL 0/6；
过度拒绝率 ORR = 1/30 = 3.3%（唯一那次是上海夜间，planner 编了池外景点）。

## 2. 三臂对照（剔除挂起样本后）

| 臂 | n | 生成规划 | OMR | soft 均分 | 中位耗时 | P95 | 输入 Token | LLM 调用 |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| A `planner_only` | 12 | 9 | 11/12（91.7%） | 79.13 | 47.5s | 68.6s | 1,961 | 1.00 |
| B `planner_reviewer` | 11 | 10 | 9/11（81.8%） | **93.22** | 68.4s | 183.5s | 7,110 | 3.08 |
| C `+time_check` | 12 | 10 | 11/12（91.7%） | 87.60 | 123.2s | 193.9s | 11,526 | 5.67 |

- **soft 质量：A 79.13 → B 93.22（+14.09）→ C 87.60（比 B 低 5.6）**。
  Reviewer 的价值在这里最清楚；Time Check 本批不但没加分，还伴随 3 次 `opening_time_conflict`（见 §4）。
- **成本**：B 相对 A 增加 2.6 倍 Token、1.7 倍耗时；C 再翻到 5.7 倍 Token、2.6 倍耗时。
- OMR 的 B 低于 A 不是"变差"：A 在负样本上直接拒绝（算 MATCH），B 把其中一个负样本
  交付成了行程（`shanghai-3d-smallpool-negative` → MISMATCH）。这正说明 OMR 必须配合
  "是否交付"一起看，而不能单独当质量指标。

## 3. Reviewer 到底消除了什么（最硬的证据）

终版 L0 码按臂统计：

| 臂 | L0 码分布 | 解读 |
|---|---|---|
| A | `route_structure` 1、`candidate_pool_preference_conflict` 1、**`unknown_poi` 1**、**`missing_must_visit` 1** | 两类是 planner 自己的错：编造池外景点、漏排点名景点 |
| B / C | `route_structure` 2、`candidate_pool_preference_conflict` 2 | 只剩负样本"本来就该拒绝"的两类 |

即：**Reviewer 把 planner 的 2 次自身错误（`unknown_poi`、`missing_must_visit`）全部消掉了**，
A 臂那两次对应的正是上海夜间（OVER_REJECT）和上海 2 小时三必去。
这是"审核不是摆设"最干净的证据——不依赖 soft_score 打分，只看码表。

## 4. Time Check 的表现（与 11-07 结论相反，需要说明）

- 本批 C 臂终版 `opening_time_conflict` 出现 **3 次**（A 臂 1 次、B 臂 1 次）。
- 11-07 的结论是"Time Check 把 PARTIAL 归零"，但那批案例不同、且当时思考链是开着的。
- 可能原因：C 臂在 Reviewer 放行后执行，遇到已放行的冲突只能记录不能重排；
  也可能这批案例的营业时间数据本身缺口更大。**当前不能写"Time Check 有效"或"无效"**，
  只能写"本批 12 例里它没有降低终版冲突数，反而增加了 Token 与耗时"。

## 5. 按案例（12 行）

| 案例 | 生成 | MATCH | soft | 三臂状态（A/B/C） |
|---|---:|---:|---:|---|
| jingdezhen-3d-sunny-history | 3/3 | 3/3 | 89.67 | SUCCESS / SUCCESS / SUCCESS |
| lijiang-3d-allrain-history | 3/3 | 3/3 | 73.39 | PARTIAL / SUCCESS / PARTIAL |
| lijiang-5d-sunny-slowpace | 3/3 | 3/3 | 95.67 | SUCCESS / SUCCESS / SUCCESS |
| nanjing-3d-singlerain-history | 3/3 | 3/3 | 88.67 | SUCCESS / SUCCESS / SUCCESS |
| nanjing-3d-sunny-history | 3/3 | 3/3 | 93.67 | SUCCESS / SUCCESS / SUCCESS |
| nanjing-3d-tighthours-negative | 3/3 | 3/3 | 93.67 | SUCCESS / SUCCESS / SUCCESS |
| sanya-1d-indooronly-empty-pool-negative | 0/3 | 3/3 | — | FAILED / FAILED / FAILED（正确拒绝） |
| sanya-3d-allrain-outdoor-negative | 3/3 | 3/3 | 62.00 | PARTIAL ×3（最低分案例） |
| **shanghai-1d-sunny-nightlife** | 2/3 | **0/3** | 89.50 | FAILED(OVER_REJECT) / PARTIAL / PARTIAL |
| shanghai-1d-twohour-three-must-negative | 0/3 | 3/3 | — | FAILED ×3（正确拒绝） |
| shanghai-3d-beyond-forecast | 3/3 | 3/3 | 89.67 | SUCCESS ×3 |
| shanghai-3d-smallpool-negative | 3/3 | 2/3 | 87.00 | SUCCESS / **MISMATCH** / PARTIAL |

- **唯一贯穿三臂的短板是上海夜间**：A 编池外景点直接失败，B/C 交付但终版带
  `opening_time_conflict` → 0/3 MATCH。这是当前系统最该修的一个用例。
- `sanya-3d-allrain-outdoor-negative` soft 只有 62.00：全程中雨 + 偏室外，虽然被判 MATCH
  （预期就是"可交付但质量差"），但它是所有案例里唯一三臂全 PARTIAL 的。
- MSR 8/12 的 4 次未命中里，**3 次来自"2 小时三必去"负样本**（本就不可能排进去），
  1 次来自上海夜间 A 臂。所以 66.7% 不代表"点名景点需求满足率"，分母需要剔除负样本。

## 6. 一次 2 小时挂起（重要工程发现）

`sanya-3d-allrain-outdoor-negative / planner_reviewer` 记录到 **latency 7066.83s（1h57m）**，
其中 planner 节点累计 **7,010,155 ms**，3 轮返工、4 次 reviewer 调用，最终仍 PARTIAL_SUCCESS。

- 现象：进程 15 秒 CPU 只涨 0.03s、4 线程在等网络 → **LLM 流式请求没有读超时**。
- 根因位置：`app/llm/openai.py` 的 `http_socket_options=()`（代码注释本身就写了
  "部分中转在流式生成时不触发读超时"），`max_tokens` 只能约束输出长度，约束不了"连接挂起"。
- 节点超时预算（`NODE_TIMEOUT_PLANNER_SECONDS=360`）没有兜住这条路径。
- 本轮处置：改为逐案例独立进程 + `timeout 480` 硬超时，其余 35 条全部正常（无超时丢弃）。

**影响口径**：这条样本纳入"是否交付/MATCH"统计，但**从延迟统计中剔除**（否则 P95 会被它吃掉）。
上表 P95 183.5s 是剔除后的值。

## 7. 雨天室外约束没有被审核兜住

`outdoor_on_bad_day_max` 规则违反次数：

| 臂 | 违反次数 | 涉及 trial |
|---|---:|---:|
| A | 7 | 3/12 |
| B | 7 | 3/12 |
| C | 5 | 2/12 |

Reviewer 与 Time Check 都没有显著减少"雨天仍然排室外"的情况。这与 §3 形成对照：
**确定性 L0（池外景点、漏排）能被返工修掉；软性天气约束基本无人管。**
当前只有 `sanya` 全雨 + 全室外这种"极端情形"才会触发 `weather_exposure_conflict` 降级。

## 8. 复现

```powershell
$env:OPENAI_THINKING="disabled"; $env:OPENAI_THINKING_PLANNER="disabled"
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --mode planner_only --mode planner_reviewer --mode planner_reviewer_time_check `
  --allow-external-calls --skip-existing --out evaluation/trials/run-20261109-expanded
..\.venv\Scripts\python.exe -m tests.eval.aggregate_trials `
  --dirs evaluation/trials/run-20261109-expanded --out evaluation/trials/run-20261109-expanded
```

## 9. 边界

- n=36（每臂 11–12），P95 仍是 12 点位的估计值，只能写"参考值"。
- 单次 k=1，不能算 pass@k；`MSR` 分母含负样本，需按 §5 修正解释。
- 全部案例来自冻结 fixture（候选池已给定），不覆盖 intent 抽取与候选补查——那部分看
  `docs/EVAL_E2E_CHAIN_20261108.md`。
- soft_score 只在 60–100 区间可比，`sanya` 62.00 与 `lijiang` 73.39 的差距含案例难度差异。
- 不能说"Time Check 无效"（案例不同、n=12）；也不能说"Reviewer 提升 14 分"是普适结论，
  本批只有 3 个案例真正发生返工。
- 7066s 那条不是"系统慢"，是**缺读超时**的工程缺陷，必须单独列，不能混进延迟分布。
