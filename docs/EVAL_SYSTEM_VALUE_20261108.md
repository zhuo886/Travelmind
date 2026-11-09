# 系统价值评测：这套编排到底做了什么（2026-11-08）

> 配置：`glm-4.5-flash`，`OPENAI_THINKING=disabled`、`OPENAI_THINKING_PLANNER=disabled`、
> `max_tokens=8000`、`structured_method=json_mode`（全部写入各 run 的 `manifest.json` 与每条 trial 的 `llm_config`）。
> 资产：`tests/eval` v3。全部为真实调用（0 stub、0 回放）。

## 1. 一句话结论

系统价值不在"一次 planner 就能出好行程"，而在**三道关卡的兜底**：

| 关卡 | 今日实测 | 作用 |
|---|---|---|
| 硬拒绝（不可行请求） | **6/6 CORRECT_REJECT**，SRR 100%、WAR 0% | 排不出来的需求不留半成品 |
| Reviewer 返工 | 交付率 **1/2 → 2/2**，soft **87 → 97** | 把 planner 的坏输出修成可交付 |
| Time Check | 交付率/OMR 不变，soft 不变，Token +50% | n=2 下边际收益未体现，只增加一致性核查 |

代价也很清楚：**关掉思考链后 Reviewer 的语义判断退化**（检出 4/5、干净样本 1/1 误打回），
这是当前配置最该修的地方。

## 2. 三臂消融（同日、同配置、同两例）

| 臂 | 模式 | trial | 生成规划 | 硬约束 HPR | 预期匹配 OMR | soft 均分 | 端到端 P50 | 总 Token | LLM 调用 |
|---|---|---:|---|---|---|---|---:|---:|---:|
| A | `planner_only` | 2 | **1/2** | 1/1 | 1/2 | 87.0 | 80.5s | 2,963 | 1.0 |
| B | `planner_reviewer` | 2 | **2/2** | 2/2 | 1/2 | **97.0** | 142.7s | 13,937 | 5.0 |
| C | `+time_check` | 2 | **2/2** | 2/2 | 1/2 | **97.0** | 138.3s | 20,906 | 8.0 |

逐条（关键差异在"能不能交出去"）：

| 案例 | A | B | C |
|---|---|---|---|
| 南京 3 天 | SUCCESS_WITH_WARNINGS · MATCH，148.8s，soft 87 | SUCCESS · MATCH，42.8s，soft 97 | SUCCESS · MATCH，134.3s，soft 97 |
| 上海 1 天夜间 | **FAILED · OVER_REJECT**，12.1s，`unknown_poi` | PARTIAL · MISMATCH，242.7s，返工 3 轮 | PARTIAL · MISMATCH，142.2s，返工 3 轮 |

解读：

- **A 臂在上海案例直接交不出东西**：planner 编了一个候选池外的景点，被硬约束拦下 → `FAILED`。
- **B 臂把它救回来**：Reviewer 打回 → 重排 → 交付 PARTIAL 行程（HPR 100%）。这就是"系统作用"最直接的证据：
  交付率 1/2 → 2/2，soft 87 → 97。
- **C 臂（Time Check）在本批没有额外收益**：OMR/soft 与 B 完全相同，Token 从 13,937 涨到 20,906（+50%）。
  与 11-07 的结论一致（Time Check 只把 PARTIAL 归零，不提高成功率），不能写成"显著提升"。
- 上海案例即便返工 3 轮，终版仍带 `opening_time_conflict` → MISMATCH，说明**返工能救"排错景点"，
  救不了"时间/营业常识"**。

## 3. 安全：不可行请求会被正确拒绝

| 指标 | 分子/分母 | 值 |
|---|---|---:|
| 不可行 trial | — | 6 |
| CORRECT_REJECT | 6 / 6 | **100%** |
| 误接受 WAR | 0 / 6 | 0% |
| 不安全交付 | 0 / 6 | 0% |
| 部分交付（不可行样本） | 0 / 6 | 0% |
| SRR | 6 / 6 | **100%** |

触发码分布：`candidate_pool_preference_conflict` 3、`route_structure` 3、`physical_time_deadlock` 2、`missing_must_visit` 1。

两个负样本本身是"下界证明不可行"的：

- 三亚 1 天全室内：候选池内 `indoor=True` 为 0 → 无解；
- 上海 1 天 2 小时 + 3 个必去：游览 180 分钟 + 直线通勤下界 92.9 分钟 > 120 分钟 → 物理不可能。

耗时：A 16.5–35.0s、B 37.0–66.4s、C 60.5–69.0s（拒绝得越早越省钱，对比 11-07 修复前 276.8s / 292.1s 的慢拒绝）。

## 4. Reviewer 能力：受控缺陷注入挑战（今日 k=1）

| 指标 | 今日（思考链关） | 11-07（思考链开，k=2） |
|---|---:|---:|
| 缺陷检出率 | **4/5（80%）** | 10/10（100%） |
| 关键词命中 | 4/5 | 10/10 |
| 干净样本误打回 | **1/1（100%）** | 0/2 |
| 双评一致 | 6/6 | 6/6 |
| 延迟 median | **10.1s** | 51.6s |
| Token | 14,796 | 32,488 |

按缺陷类型：`unknown_poi` ✅、`duplicate_poi` ✅、`overpacked` ✅、`weather_outdoor` ✅、
**`missing_must_visit` ❌ 漏检**。

干净样本（南京、天气正常、无注入缺陷）被判 `reject`，理由是"Day3 的中山陵景区和总统府周一闭馆"——
该行程实际是周二到周四，而且 Reviewer prompt 明确禁止它评审开放时间。11-07 记录的是
"通过但说了同样的错话"，**关掉思考链后退化成"直接按错话误打回"**。

结论：Reviewer 对显性结构缺陷（池外景点、重复、超量、全雨全露天）仍然可靠，对
"需要多步推理的漏排/礼拜推理"不可靠；10 秒的延迟是省下来的，但省在了判断力上。

## 5. 语义质量：真实 Judge（今日 k=2）

| 指标 | 今日（5 条） | 11-07（15 条） |
|---|---:|---:|
| 有效评分 | 5/6（1 条跳过：A 臂上海无路线） | 15/15 |
| 总分均值 | **79.2** | 78.73 |
| 双评 kappa | 1.0（见边界） | 0.5975 |
| Judge 调用 / Token | 10 / 11,521 | 30 / 37,126 |
| 按案例 | 南京 80.0、上海 78.0 | 南京 84.5、上海 79.0 |

维度（0–5）：`time_realism` 5.0、`pacing` 4.6、`preference_fit` 4.0、
`completeness` 3.6、`diversity_and_dining` 3.2、`geographic_coherence` 3.0。

flags：`missing_transport` 3、`other` 3、`geographic_inefficiency` 1、
`incomplete_practical_info` 1、`missing_dining` 1、`preference_mismatch` 1。

解读：语义总分与 11-07 同级（79.2 vs 78.73，样本不同，**不能当提升**）；最低维度仍是
地理连贯性与多样性，说明这两个短板与思考链开关无关，属于产品结构问题。

## 6. 这套系统"作用"到底体现在哪

1. **不交付错误答案**：不可行请求 6/6 硬拒绝，不留半成品；A 臂排了池外景点会被拦成 FAILED 而不是交出去。
2. **把失败变成可交付**：同一案例 A 交不出、B 能交出（1/2 → 2/2），代价是 4.7 倍 Token。
3. **缺陷可被定位**：L0/L1 码表 + snapshot 轨迹能说清"错在哪一步"，而不是只给一个失败。
4. **质量可被独立度量**：deterministic `soft_score`（结构/偏好/节奏）+ 语义 Judge（路线合理性）
   两把尺子分开，不互相替代。

## 7. 复现

```powershell
$env:OPENAI_THINKING="disabled"; $env:OPENAI_THINKING_PLANNER="disabled"
# A 臂
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --case nanjing-3d-sunny-history --case shanghai-1d-sunny-nightlife `
  --mode planner_only --allow-external-calls --out evaluation/trials/run-20261108-ablation-a
# 安全负样本（2 例 × 3 模式）
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --case sanya-1d-indooronly-empty-pool-negative --case shanghai-1d-twohour-three-must-negative `
  --allow-external-calls --out evaluation/trials/run-20261108-safety-r5
# 语义 Judge
..\.venv\Scripts\python.exe -m tests.eval.judge `
  --trials evaluation/trials/run-20261108-think-off-r4 --trials evaluation/trials/run-20261108-ablation-a `
  --version v3 --provider llm --k 2 --max-calls 20 --allow-external-calls `
  --out evaluation/judge/run-20261108-thinking-off
# Reviewer 受控挑战
..\.venv\Scripts\python.exe -m tests.eval.reviewer_challenge --version v3 --k 1 `
  --allow-external-calls --out evaluation/reviewer_challenge/run-20261108-thinking-off
```

## 8. 边界（不得越界表述）

- **n 极小**：三臂各 2 条、安全 6 条、Judge 5 条、挑战 6 次。只能作方向与机制证据，不能写"成功率 X%"。
- 今日挑战是 **k=1**，11-07 是 k=2，检出率不可直接做显著性比较；只能说"今日这轮漏了 1 类"。
- 干净样本只有 1 个，"误打回 100%"只是 1/1，不能外推误打回率。
- Judge 今日 kappa=1.0 是 `temperature=0` 下同一模型两次调用完全一致，**不构成"评委可靠"的证据**；
  真实一致性参考 11-07 的 0.5975。
- Judge 覆盖率 5/6：A 臂上海没有路线，无法盲评，已在分母外。
- Token 全是估算值，不是账单；C 臂 Token 高于 B 是重试导致，不是 Time Check 稳性成本。
- 不能写"Time Check 无效"：n=2，且历史 30 例里它把 PARTIAL 归零；本轮只能说"本批无额外收益"。
- 不能写"关思考链质量不变"：deterministic soft_score 不变，但 Reviewer 语义能力与受控检出率下降。
