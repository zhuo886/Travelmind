# Travelmind 评测口径 v4：简历指标可复核化

> 版本：v4（2026-11-07）。v1/v2/v3 的 spec、结果与原始 trial 全部保持冻结，本文件只定义增量。
> 本轮 Planner / Reviewer / Judge 真实调用 **0 次**；全部为离线回放、prompt 捕获或 IO 等待仿真。
> 产物目录：`evaluation/benchmarks/{route_parallel,modify_budget,candidate_budget,policy,adaptive,gap_fill,sse}`。

## 0. 为什么需要 v4

v3 之前的评测能回答"规划质量如何"，但不能回答简历里的四类工程指标：

| 简历写法 | 原先的问题 | v4 的处理 |
|---|---|---|
| 通路校验 P50 加速 6.79× | 仓库无并发对照基准 | 新增串行/并发同节点对照，测调度加速比 |
| checkpoint 重规划 −31.8% / 输入预算 −15.2% | E2 两臂同子图，检索阶段没进分母 | 改为"全量重规划入口 vs 修改入口"的 prompt 精算 |
| 任务成功率 86.7%→100% | 本仓库无 30 例真实四臂 | 用已冻结 trial 做四臂**回放**，并做增益归因 |
| 自适应跳过省 Token 61.8% | 当前门控跳过率恒为 0 | 明确证伪，并给出放宽策略的对照数据 |
| pytest 501 项 | 本仓库实测 134 → 178 | 如实报告实测值 |

## 1. 五组实验的口径

### 1.1 并发通路校验（`tests/eval/route_benchmark.py`）

- 被测对象：`app.planning.nodes.route_distance_check_node`（生产代码，未复制逻辑）。
- 串行臂：把该节点的 `ThreadPoolExecutor` 换成单线程池；并发臂用节点原生 `min(8, N)`。
- 单次调用用注入延迟代替真实高德请求。
- **加速比是调度属性**：只要单次调用是纯等待，speedup 只取决于段数与并发度，与注入延迟绝对值无关。
  因此"三档延迟下 speedup 基本一致"是仿真正确性的自检条件（`self_check.passed`）。
- 可选 `--sample-external` 采样真实单次耗时，写入 `samples.json`，仅作量级参照，**不参与**加速比。

### 1.2 Checkpoint 修改输入预算（`tests/eval/modify_budget.py`）

- A 臂入口：`intent` → `query_rewrite` → (`candidate_react`) → `planner`。
- B 臂入口：`planner`（`build_modification_graph` 的起点）。
- 做法：patch 掉 LLM 客户端、调用**真实节点函数**，捕获真实构造出的 prompt，再用
  `app/core/llm_usage.py:estimate_tokens` 计数。
- B 臂必须把"上一版路线"计入 prompt 成本，不允许只算省下的部分。
- **耗时不做推算**：仓库内没有检索阶段的实测耗时，凭空补一个延迟等同伪造；
  耗时结论以 27 组真实 E2 配对为准，并单独标注。

### 1.3 有界 ReAct 合规与幻觉阻断（`tests/eval/candidate_budget.py`）

纯聚合，只读已冻结 trial 的落盘字段：

- 预算合规：`candidate_api_calls ≤ 10`、`candidate_search_round ≤ 2`。
  **两个口径分开报**：已冻结 trial 的 `candidate_api_calls` 恒为 0（harness 从 planner 起跑），
  trial 口径必须标 **N/A**——把 0 次检索算成 100% 是空转指标；
  真正跑过真实执行器的是 `gap_fill_ablation` 的 `bounded_react` 臂，
  那里 28/28 场景合规、单场景最多 2 次。
- 幻觉阻断分三层：引用级（`oor`）、trial 级（`unknown_poi` 的 L0）、拦截级
  （首版有 `unknown_poi` 且最终 L0 为空）。
- 去重与缓存命中依赖 `candidate_search_trace`；旧 trial 未落盘该字段时一律 **N/A**，不用 0 代替。
  该字段自 v4 起由 `run_trials` 补写，下一轮运行才有数据。

### 1.4 候选补查离线消融（`tests/eval/gap_fill_ablation.py`）

- 28 个受控场景：`named` / `indoor` / `count` / `boundary` 各 7 个。
- 两臂：`seed_only`（只用给定池）与 `bounded_react`（真实决策队列 + 真实执行器 + 桩化检索）。
- 缺口按"缺口单元"计数（`named:<景点>` / `indoor` / `count` / `other:<类型>`），
  报告"修复"与"新增缺口"两个方向。
- `boundary` 场景代表池里与检索源都不存在的请求，正确结果是**补不上**；
  若出现修复则为缺陷（`boundary_false_fix` 必须为 0）。
- 本实验只测决策/预算/去重逻辑，**不代表高德召回率**。

### 1.5 SSE 流式时序（`tests/eval/sse_timing.py`）
- 被测对象：`app.planning.graph.run_stream` 的事件转发层，节点替换为固定延迟桩。
- 指标：`TTFE`（到第一条 `stage` 的时间）、整轮耗时、事件数、顺序不变量违反数。
- 顺序不变量：同节点的 `stage` 先于 `stage_summary`；`result` 唯一且在最后；未挂文案的节点被过滤。
- TTFE 只是框架开销，**不能**当线上首字延迟。

## 2. ESR 定义（四臂回放用）

```
可行案例（expected_feasible != False）：
  ESR 成功 = 交付路线非空
          且 l0_codes 为空
          且 l1_codes 与 {physical_time_deadlock} 无交集
          且 benchmark_label == "MATCH"

不可行案例（expected_feasible == False）：
  ESR 成功 = actual_outcome == "CORRECT_REJECT"
```

`PARTIAL` 不算成功。同时必须报 OMR / HPR / PDR，避免单一成功率掩盖问题。

## 3. 四臂回放（`tests/eval/production_policy.py`）

| 臂 | 来源 | 说明 |
|---|---|---|
| A | `planner_only` 记录 | 真实结果 |
| B | `planner_reviewer` 记录 | 真实结果 |
| C | `planner_reviewer_time_check` 记录 | 真实结果 |
| D | 回放 | 把 A 的首版路线喂给真实 `route_risk_gate_node`；跳过则沿用 A，否则沿用 C |

D 臂是**回放近似**：审核节点看到的状态与真实运行不同，不能当新一轮实测。
本批 5 个 case 全部需要审核（skip 0/5），因此 D ≡ C。
草稿级门控另外用 **30 份草稿**（trial 15 + checkpoint 15）统计，不受 A/B/C 配对限制。

### 增益归因

不用 `snapshot_trace.rework_requested`（旧记录恒为 False），改用可复核的三件字段：

- `planning_revision_rounds > 0` 视为发生返工；
- `first_draft_l0` 非空 → 规则驱动；返工后 `l0_codes` 为空 → 规则修复成功；
- 首版就无 L0 却仍返工 → 语义/软约束驱动。

## 4. 自适应跳过（`tests/eval/adaptive_review.py`）

- 样本：30 份草稿（trial 15 + checkpoint 15）。
- 现状策略：`semantic_review=True`（任何含偏好的 query 强制升级审核）。
- 对照策略：`semantic_review=False`（只看确定性 flag）。**不是产品默认**。
- 指标：`skip_rate`、`false_skip_rate`（被跳过且草稿自带 L0/不可交付 L1）、
  `token_saved_counterfactual`（跳过时省掉同 case 的审核增量）。
- checkpoint 草稿无 `l0_codes`，误跳过只在“缺陷已知”子集上统计；同 case 多份草稿共用同一增量，故 Token 合计为上限。
- 反事实节省 ≠ 账单节省：主体规划成本不变。

## 5. N/A 纪律

| 情况 | 处理 |
|---|---|
| 旧 trial 无 `candidate_search_trace` | 去重/缓存命中 = N/A，并写明原因 |
| `candidate_api_calls` 全为 0 | 预算合规 = N/A（检索未被触及，100% 是空转） |
| 仓库无检索阶段实测耗时 | 修改类耗时 = `partial_decomposition`，全链路标 `not_measured` |
| `REDIS_URL` 未配置 | 缓存命中率只作 fake redis 单元结果，不报生产命中率 |
| 无人工标签 | Judge 校准 = N/A（沿用 v3） |

## 6. 工程化与可观测（对应第 4 条 bullet）

### 6.1 缓存埋点

- `app/core/cache.py`：模块级 hit/miss/disabled/error 计数与 `cache_snapshot()`，
  只在 `get_cached` 返回值分支 +1；**不改** key、TTL、降级行为。
- `/api/metrics` 追加 `travelmind_cache_hits_total{result="hit|miss|disabled|error"}`，
  “缓存有没有用”从推测变成可查询。
- `tests/test_cache_metrics.py` 用进程内 fake redis 验 hit/miss/disabled/error，
  并用 `TestClient` 验 `/api/metrics` 行格式。

### 6.2 SSE 时序

- `tests/eval/sse_timing.py` 用桩节点跑 `run_stream`，测 TTFE、事件数、顺序不变量。
- 另用 `TestClient` 打 `/api/plan/stream` 验 HTTP 层帧形状；`TestClient` 会缓冲响应，
  因此 TTFE 只由进程内测量提供，HTTP 层不声称延迟。
- 与 `tests/test_sse_contract.py` 互补（契约 vs 时序），不重复断言。
- 只报“框架开销 + 序列合规率”，不报线上首字延迟。

### 6.3 语义记忆

`tests/test_semantic_memory.py` 覆盖：`SEMANTIC_MEMORY_ENABLED=0` 短路、
不同 `user_id` 不串味、同事实去重、检索失败降级为 `degraded`。

## 7. 结果文档

| 实验 | 结果文档 |
|---|---|
| 并发通路校验 / checkpoint 预算 | `docs/EVAL_RESULTS_V4_MODIFY.md` |
| 检索合规 / 补查消融 | `docs/EVAL_RESULTS_V4_RETRIEVAL.md` |
| 四臂回放 / 归因 | `docs/EVAL_RESULTS_V4_POLICY.md` |
| 自适应跳过 | `docs/EVAL_RESULTS_V4_ADAPTIVE.md` |
| SSE / 缓存 / 语义记忆 | `docs/EVAL_RESULTS_V4_ENGINEERING.md` |
| 简历映射 | `docs/RESUME_EVIDENCE.md` |

## 8. 复现命令

```powershell
..\.venv\Scripts\python.exe -m pytest -q tests

..\.venv\Scripts\python.exe -m tests.eval.route_benchmark --out evaluation/benchmarks/route_parallel
..\.venv\Scripts\python.exe -m tests.eval.modify_budget --out evaluation/benchmarks/modify_budget
..\.venv\Scripts\python.exe -m tests.eval.candidate_budget --out evaluation/benchmarks/candidate_budget
..\.venv\Scripts\python.exe -m tests.eval.production_policy --out evaluation/benchmarks/policy
..\.venv\Scripts\python.exe -m tests.eval.adaptive_review --out evaluation/benchmarks/adaptive
..\.venv\Scripts\python.exe -m tests.eval.gap_fill_ablation --out evaluation/benchmarks/gap_fill
..\.venv\Scripts\python.exe -m tests.eval.sse_timing --out evaluation/benchmarks/sse
```
