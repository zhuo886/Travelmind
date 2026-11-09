# Checkpoint 修改：输入预算与耗时拆解

> 口径：捕获两臂**真实构造出的 prompt**，用 `estimate_tokens` 计数；0 次 LLM 调用
> A 臂 = 全量重规划入口（intent + query_rewrite + planner，含缺口时的 candidate_react）
> B 臂 = checkpoint 增量修改入口（仅 planner，但 prompt 内含上一版路线）

## 1. 输入预算

- 有效 case：5
- A 臂 token 均值 / 中位：3346.8 / 3215
- B 臂 token 均值 / 中位：2836.6 / 2826
- 变化：-15.2%（负数=更省）
- LLM 调用数中位：A 3 → B 1

### 逐调用（token 中位）

| 调用 | 样本数 | token 中位 |
|---|---:|---:|
| A:CandidateDecision | 2 | 877.5 |
| A:IntentExtraction | 5 | 264 |
| A:RewrittenQuery | 5 | 255 |
| A:TravelRoute | 5 | 2692 |
| B:TravelRoute | 5 | 2826 |

### 逐 case

| case | A token | A 调用 | B token | B 调用 | 变化 |
|---|---:|---:|---:|---:|---:|
| lijiang-5d-sunny-slowpace | 3215 | 3 | 3263 | 1 | +1.5% |
| nanjing-3d-sunny-history | 2957 | 3 | 2757 | 1 | -6.8% |
| shanghai-1d-sunny-nightlife | 3219 | 3 | 2826 | 1 | -12.2% |
| nanjing-3d-tighthours-negative | 2866 | 4 | 1988 | 1 | -30.6% |
| sanya-3d-allrain-outdoor-negative | 4477 | 4 | 3349 | 1 | -25.2% |

- B 臂反而更贵的 case：1 / 5（lijiang-5d-sunny-slowpace）
- 原因：B 臂 planner prompt 里含完整上一版路线，天数越多、路线越长，这笔开销越可能抵消省下的 intent/query_rewrite。

## 2. 耗时

- 全链路状态：**not_measured**
- 原因：仓库内没有检索阶段（attraction_search/candidate_search）的实测耗时，补一个延迟即伪造；因此只给已测节点的拆解，全链路 P50 仍标 not_measured

### 2.1 阶段拆解（仅已测节点）

| 阶段 | 节点数 | 已测 | 估算耗时 | 占已测总量 | B 臂是否执行 |
|---|---:|---:|---:|---:|---|
| intake | 3 | 0 | 0ms | N/A | 否 |
| retrieval | 5 | 0 | 0ms | N/A | 否 |
| planning | 2 | 1 | 93695.8ms | 37.3% | 是 |
| review | 3 | 2 | 157725.8ms | 62.7% | 是 |
| finishing | 3 | 0 | 0ms | N/A | 是 |

- A 臂已测覆盖：0.188（251421.6ms）；未测：['intent', 'query_rewrite', 'weather_search', 'attraction_search', 'candidate_react', 'candidate_search', 'candidate_validator', 'main_meal_search', 'route_distance_check', 'risk_gate', 'main_meal_output', 'spot_tips', 'finalize']
- B 臂已测覆盖：0.375（251421.6ms）；未测：['route_distance_check', 'risk_gate', 'main_meal_output', 'spot_tips', 'finalize']
- 两臂的已测节点几乎相同（planner/reviewer/time_check），所以这张表**不能**推出耗时降幅；它只说明哪些阶段根本没有耗时数据。

### 2.2 E2 真实配对参照（同子图，27 组）

- 重规划 P50 降幅：+11.7%（正数=更快）
- 输入 Token 降幅：-6.6%（负数=反而更多）
- 未修改内容保留率：A +73.5% → B +90.6%

> 该配对两臂都从 `planner` 起跑，检索阶段没进分母，所以它证明的是“不跳过检索时确实不省”，不能当成全链路收益。

## 3. 读法

- 只能说“入口输入预算下降 X%”，不能说“重规划耗时降低 X%”（耗时本轮未测）。
- B 臂 planner prompt 更大（含上一版路线），因此不能只报省下的部分。
- 若 X 为正（B 更贵），说明 checkpoint 的价值在保留率与硬约束，不在 Token。