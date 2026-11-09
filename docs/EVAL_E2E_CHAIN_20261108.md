# 端到端真实链路评测（2026-11-08）

> 脚本：`python -m tests.eval.e2e_chain --allow-external-calls`
> 产物：`evaluation/benchmarks/e2e/`（每例一份 JSON + summary.json + REPORT.md）
> 配置：`glm-4.5-flash`、`OPENAI_THINKING=disabled`、`OPENAI_THINKING_PLANNER=disabled`、`max_tokens=8000`、`json_mode`

## 1. 为什么要有这一组

前面所有结论（A/B/C 消融、安全、Reviewer 挑战）都建立在**冻结候选池**上：`run_trials` 直接喂
fixture 的 POI 列表，跳过 intent 抽取、查询改写、天气/餐饮检索、候选补查、路距校验。
这一组反过来，走生产 `run_stream`：真实高德 API + 真实意图抽取 + 真实候选池，只冻结用户输入。

它回答的是另一类问题：**链路能不能跑通、哪一步在拖时间、真实输入下会不会暴露静默缺陷。**

## 2. 冻结输入与结果（4 例，0 异常）

| 案例 | 输入 | 结果 | 天数 | 景点 | 端到端 | LLM 调用 | 输入 Token |
|---|---|---|---:|---:|---:|---:|---:|
| hangzhou-1d-date-hint | 杭州一日，西湖边慢慢走，11.18开始 | ✅ PARTIAL_SUCCESS | 1 | 3 | 208.0s | 13 | 41,195 |
| chengdu-weekend-tea | 成都周末两天，想泡茶馆吃火锅，明天中午开始 | ✅ PARTIAL_SUCCESS | 2 | 6 | 241.7s | 9 | 30,312 |
| nanjing-3d-history | 南京三天，想看历史建筑和博物馆，节奏慢一点，别太赶 | ❌ FAILED（clarify） | 0 | 0 | 8.6s | 1 | 265 |
| vague-request-clarify | 我想出去玩几天，你看着安排 | ❌ FAILED（clarify） | 0 | 0 | 5.4s | 1 | 259 |

产出路线：

- 杭州：杭州西湖风景名胜区 → 灵隐寺 → 中国丝绸博物馆（单日、3 点，符合"慢慢走"）
- 成都：空山茶事·三国馆 → 成都武侯祠博物馆 → 交子金融博物馆 → 四川大学博物馆 → 成都杜甫草堂博物馆 → 水井坊博物馆
  （"泡茶馆"落到空山茶事，火锅进了 meal_slots 而不是景点，语义正确）

日期兜底在真实链路生效：`11.18` 被解析为 2026-11-18（模型没给日期时由 `parse_explicit_travel_dates` 兜底），
`周末两天 + 明天中午开始` 以"明天"为起点（优先级：今天/明天 > 周末）。

## 3. 节点耗时画像（4 例实测）

| 节点 | 杭州 | 成都 | 说明 |
|---|---:|---:|---|
| intent | 4.6s | 6.0s | 含一次结构化调用 |
| weather_search | 0.26s | 0.28s | 高德天气 |
| main_meal_search | 0.45s | 0.43s | 20 个餐馆候选 |
| query_rewrite | 4.2s | 6.4s | |
| attraction_search | 0.63s | 0.59s | 15 个候选 |
| candidate_react | 2.6s | 11.4s | 多轮 ReAct 补查 |
| **planner（累计）** | **30.0s** | **59.6s** | 成都 4 轮草案 |
| **reviewer（累计）** | **73.9s** | **41.9s** | 杭州含结构化降级重试 |
| route_distance_check | 0.54s | 0.56s | 8 段道路距离 |
| risk_gate | 7ms | 12ms | 纯规则，几乎免费 |
| finalize_direct | 2.1s | 2.5s | |

结论：**耗时几乎全部落在 planner 与 reviewer 两个 LLM 节点**；确定性节点（risk_gate 7–12ms、
snapshot 5–15ms、路距 0.5s）加起来不到 1 秒。想优化端到端，只有两条路：减少返工轮次、或换更快模型。

## 4. 五个真实发现（都是 frozen fixture 测不出来的）

### 4.1 结构化降级在真实链路被触发（工程价值）

```
[structured] method=json_mode 返回 None parsing_error=OutputParserException finish_reason=stop
[structured] 已切换到可用方法 method=function_calling
[invoke_structured] RouteReview 第 2 次重试后成功，本次耗时 19.80s
```

`json_mode` 偶发返回不可解析内容，三级降级自动切到 `function_calling` 并成功。没有这个机制，
这一轮就是整单失败。这是"对抗不稳定上游"的直接证据，不是设计文档里的假设。

### 4.2 `time_check` 在生产路径可能根本不执行（架构缺口）

四例的节点序列里**没有 `time_check`**。原因是它挂在"Reviewer 放行之后"：只要 Reviewer 一直打回，
专项核查就永远不会跑。成都案例正好是这种情况——Reviewer 连续 4 轮打回、未收敛，最后靠
`max_review_rounds` 收尾交付，全程没做开放时间核验。

影响：消融实验里 C 臂（强制 time_check）的收益，在真实链路里取决于 Reviewer 是否放行；
"加了 Time Check 就一定多一层校验"不成立。

### 4.3 Reviewer 会不收敛（成都：4 轮全打回）

```
planner 1 轮 6 景点 → reviewer 打回
planner 2 轮 6 景点 → reviewer 打回
planner 3 轮 6 景点 → reviewer 打回
planner 4 轮 6 景点 → reviewer 打回 → 收尾
```

景点集合四轮都没变（6 个），Reviewer 每次都说"发现 1 项需调整"，属于典型的**无法收敛**：
既没有把问题说成 planner 能执行的修改，也没有在第二轮就放弃。最终交付 PARTIAL，
`route_issues` 里留下 5 项风险。

### 4.4 「只给天数不给日期」时天数被丢弃（可修缺陷）

输入「南京三天，想看历史建筑和博物馆」→ 系统追问"出行开始日期 + 出行结束日期"，但**天数用户已经给了**。

定位：`app/planning/nodes.py:204` 已算出 `travel_days_hint = result.travel_days or extract_travel_days(query) = 3`，
但 `nodes.py:207` 只在 `start` 存在时才用它推算 `end`；`start` 缺失时 `days` 保持 0，
`missing` 于是同时追加"开始日期"和"结束日期"。

修法（未改代码，待确认）：`travel_days_hint > 0` 时，`missing` 只追加"出行开始日期"；
用户补了日期后自动得到 `end` 与 `days`。期望行为是问一次，而不是问两次。

### 4.5 clarify 行为符合预期（安全侧）

「我想出去玩几天，你看着安排」→ 只花了 5.4s、1 次调用就停下并追问"目的地 + 日期"，
没有编造目的地，也没有硬凑一个行程。这是"宁可追问也不瞎编"的直接证据。

## 5. 复现

```powershell
$env:OPENAI_THINKING="disabled"; $env:OPENAI_THINKING_PLANNER="disabled"
..\.venv\Scripts\python.exe -m tests.eval.e2e_chain --allow-external-calls
# 只跑某几例（同目录会自动合并已有 e2e_*.json）
..\.venv\Scripts\python.exe -m tests.eval.e2e_chain --case hangzhou-1d-date-hint --allow-external-calls
```

## 6. 边界

- **n=4**，只能当"链路可用性 + 缺陷发现"，不能算成功率。
- 同一案例重复跑波动明显：杭州 367.5s（首轮）/ 637.8s（次轮，含 190s 降级重试）/ 208.0s（第三轮）。
  不是环境噪声，是 planner/reviewer 的 LLM 抖动 + 重试。
- 高德接口偶发失败：成都首轮 `route_distance_check` 有"6/8 段成功、2 段失败"，重排后 8/8。
- Token 为估算值；`glm-4.5-flash` 的实际账单需另算。
- 真实链路里 `time_check` 未执行属于**路径门控**，不是节点缺失；不能写"系统缺少时间校验"。
- 「南京三天」是**天数兜底未接入 missing 判定**，不是"系统不会解析三天"（`extract_travel_days` 单独测是 3）。
