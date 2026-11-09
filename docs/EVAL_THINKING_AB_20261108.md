# 思考链开关：速度与质量对照评测（2026-11-08 补测版）

> 目的：回答"重新跑评测后速度变快、质量有没有变化，是不是因为关了思考模式"。
> 资产：`tests/eval` v3（`benchmark_v3` + `fixtures_v2/v3`）；对照组固定两例
> `nanjing-3d-sunny-history`、`shanghai-1d-sunny-nightlife`；模式 B `planner_reviewer` +
> C `planner_reviewer_time_check`，k=1；模型 `glm-4.5-flash`（智谱 `open.bigmodel.cn`）。
> **本版新增**：trial/manifest 记录 `llm_config`；补一套配置可自证的"全关"对照（`think-off-r4`）。

## 1. 结论速览

| 观测 | 全关（今日，n=9） | v1 历史（11-06，n=16） | 变化 |
|---|---:|---:|---|
| 端到端 P50 | **134.3s** | 193.8s | **-30.7%** |
| reviewer P50 | **25.1s** | 79.0s | **-68.2%** |
| time_check P50 | **10.0s** | 38.2s | **-73.8%** |
| planner P50 | 79.1s | 65.3s | +21.1%（没变快） |
| soft_score 均值 | **96.44** | 94.88 | +1.56（没有下降） |
| MATCH | 5/9 | 16/16 | 明显下降 |
| 终版 `opening_time_conflict` | **4/9（上海 4/4）** | 0/16 | 夜间类必现 |
| 平均返工轮次 | 1.67 | 0.69 | 返工更多但仍未修好 |

一句话：**加速来自 Reviewer / Time Check 关掉思考链，Planner 关思考链并未变快；确定性
soft_score 没掉，掉的是语义类约束（上海夜间营业时间冲突 4/4 留在终版）。**

## 2. 今日各次运行（配置自证）

| 组 | 目录 | llm_config | n | 端到端P50 | planner | reviewer | time_check | soft | MATCH | 终版 open_conf |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 16:36 批 | `run-20261108-thinking-off` | 未记录（不可自证） | 4 | 194.1s | 118.2s | 47.6s | 23.4s | 95.75 | 0/4 | 2/4 |
| 17:02 r3 | `run-20261108-thinking-off-r3` | 未记录 | 4 | 111.7s | 72.7s | 33.9s | 10.0s | 95.75 | 2/4 | 2/4 |
| 19:04 r4 | `run-20261108-think-off-r4` | `thinking_global=disabled`、`thinking_planner=False`、`max_tokens=8000`、`json_mode` | 4 | 138.3s | 105.5s | 22.1s | 10.3s | 97.00 | 2/4 | 2/4 |
| 17:47 补跑 | `probe-think-off` | 同上 | 1 | 238.9s* | — | — | — | 97.00 | 1/1 | 0/1 |

`*` 含两轮 429 退避，纯计算约 60–90s，不能当典型值。

`think-off-r4` 逐条：南京 B SUCCESS·MATCH 42.8s、南京 C SUCCESS·MATCH 134.3s、
上海 B PARTIAL·MISMATCH 242.7s、上海 C PARTIAL·MISMATCH 142.2s。

## 3. 历史基线（可直接对比的旧指标）

| 数据集 | 规模 | 端到端/Mode P50 | soft | OMR | 备注 |
|---|---|---:|---|---|---|
| v1 主消融 `run-20261106/final` | 66 trial | 66.5 / 256.1 / 294.2s | 77.19 / 84.50 / 87.53 | 36.4 / 68.2 / 68.2% | 节点 P50：planner 85.3、reviewer 100.6、time_check 65.9 |
| v1 S2-only | 30 trial | 62.7 / 258.4 / 300.6s | 78.17 / 85.20 / 85.77 | 40 / 80 / 80% | 主消融口径 |
| v4 四臂回放 `benchmarks/policy` | 5 例 | A 99.6 / B 249.6 / C 236.3s | — | ESR 40 / 60 / 60% | Token ×3.02、P50 ×2.37 |
| v3 Judge `judge/run-20261108` | 15 条×k=2 | — | 78.73 分，κ=0.5975 | — | 语义评委，与 soft_score 不同尺 |

上文"v1 历史（n=16）"= 上述 66 trial 中与今日同两个案例的 B/C 子集，用于同案例对照。

## 4. 质量细分：缺陷分布

| 组 | L0（终版） | L1（终版） | 平均返工轮次 |
|---|---|---|---|
| v1 历史 n=16 | 空 | 空 | 0.69 |
| 全关 n=9 | 空 | `opening_time_conflict` × 4 | 1.67 |

- 硬约束（L0）两组都为 0：关思考链没有让系统排不存在的景点、也没破坏时间结构。
- 唯一的终版缺陷是 `opening_time_conflict`，且集中在上海夜间案例：B/C 两个模式、两次
  独立运行（r3、r4）全部 2/2 命中，说明**不是单次抖动**。
- 返工轮次从 0.69 升到 1.67：Reviewer 在无语义推理时更频繁地要求返工，但没能修掉这个问题。

## 5. 阻塞：planner 思考链在当前配额下不可用（4 次复现）

| 次 | 时间 | 目录 | 结果 |
|---:|---|---|---|
| 1 | 17:05 | `run-20261108-planner-thinking` | 进程退出、0 产物 |
| 2 | 17:22 | `run-20261108-think-planner-on` | 242.00s → 429；重试全部 429 |
| 3 | 17:39 | `probe-think-on` / `probe-think-on-nomax` | 121.92s / 122.00s → 429（去掉 `OPENAI_MAX_TOKENS` 同样复现） |
| 4 | 19:05 | `run-20261108-think-on` | 241.99s → 429；重试后又出现 **361.63s `OpenAITimeoutError`**（planner 节点预算 360s）与 121.89s → 429；第 3 次退避时人工终止 |

统一形态：`TravelRoute` 第 1 次调用跑满 ~121s / ~242s 后抛 `OpenAIRateLimitError`
（`您的账户已达到速率限制`），或跑满 360s 撞 planner 节点预算抛 `OpenAITimeoutError`；随后
2–3 分钟内所有调用 429，之后自愈。原始日志保留在 `evaluation/trials/think-on.log`。

反驳性对照：同一时刻、同一案例、只把思考链关掉即成功（`probe-think-off` 与 `think-off-r4`
均在 17:47 / 18:54 正常完成）。**结论：不是账号被封，也不是输出上限，而是带思考链的
planner 请求本身超出当前配额。**

## 6. 本轮代码改动（评测侧，不涉产品逻辑）

1. `tests/eval/run_trials.py`
   - 新增 `_llm_config_snapshot()`：记录 `model / provider / thinking_global / thinking_planner / max_tokens / structured_method`。
   - `manifest.json` 增加 `llm_config`；**每条 trial 也写入 `llm_config`**，从此可自证配置。
2. `tests/test_eval_trial_config.py`（新增，3 个用例）：开关读取、planner 覆盖全局、类型稳定。
3. 回归：全量 `pytest -q tests` → **196 passed**（含新增 3 个用例）。

未修改：`app/` 下任何产品代码；`.env.local` 未改（ON/OFF 用进程级环境变量覆盖，
`load_local_env` 不覆盖已存在的 `os.environ`）。

## 7. 复现

```powershell
# 全关（本版 r4 的命令，配置会写进 manifest 与 trial）
$env:OPENAI_THINKING="disabled"; $env:OPENAI_THINKING_PLANNER="disabled"
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --case nanjing-3d-sunny-history --case shanghai-1d-sunny-nightlife `
  --mode planner_reviewer --mode planner_reviewer_time_check `
  --allow-external-calls --out evaluation/trials/run-20261108-think-off-r4

# planner 单独开（当前配额下必然 429，仅作证据）
$env:OPENAI_THINKING="disabled"; $env:OPENAI_THINKING_PLANNER="enabled"
..\.venv\Scripts\python.exe -m tests.eval.run_trials --version v3 `
  --case nanjing-3d-sunny-history --mode planner_reviewer `
  --allow-external-calls --out evaluation/trials/run-20261108-think-on
```

## 8. 边界（不得越界表述）

- **跨天对比只能看方向**：v1 是 11-06 的代码与 v1 资产；11-08 另有 hotel anchor
  （`app/api/plan_routes.py` 15:47）、graph 预算（`app/planning/graph.py` 15:04）与思考链开关改动。
  要写因果只能用同日 r4 的配置与逐条结果。
- **16:36 批与 r3 的 env 不可自证**（当时产物不记配置），只能由 planner 延迟（118.2s vs 72.7s）反推；
  正式口径只用 r4 及其后产物。
- **n 很小**：全关合计 9 条，其中"配置可自证"的只有 5 条；单模式 k=1，不能算 pass@k。
- soft_score 只在 87–100 档可比，不能说"质量整体提升 1.56 分"。
- 正确表述是"关思考链对 planner 没有加速作用"，不能反过来说"planner 变慢了 21%"（受慢样本影响）。
- `opening_time_conflict` 4/4 只覆盖上海夜间 1 个案例，不能外推为"所有夜间需求都会错"。

## 9. 下一步

1. 上海夜间案例的修法不要依赖"把 planner 思考链开回来"：在候选池/校验层加
   "夜间偏好 × 闭馆时间"的确定性检查（可作为 L1 生成源，让 Reviewer 有据可依）。
2. 若要验证 planner 思考链的实际质量收益，需换模型或更高配额，再跑同样 4 条。
3. 配额可用后把本研究扩到 10 例 × B/C（20 条），才够写进简历。
