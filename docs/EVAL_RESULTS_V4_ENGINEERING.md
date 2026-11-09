# v4 结果：工程化与可观测

> 脚本：`python -m tests.eval.sse_timing`
> 代码：`app/core/cache.py`、`app/core/observability.py`、`tests/test_cache_metrics.py`、`tests/test_semantic_memory.py`
> 口径：`docs/EVAL_SPEC_V4.md` §6
> 本轮 0 次外部调用：SSE 用桩节点，缓存用进程内 fake redis

## 1. 测试规模

| 项 | 值 |
|---|---:|
| 全量测试 | **178 passed** |
| 基线（v3 收尾） | 134 |
| 本轮新增 | 43 |
| 网络依赖 | 0 |

## 2. SSE 转发层

| 指标 | 值 | 说明 |
|---|---:|---|
| 首事件延迟 TTFE（P50） | **≈0.1ms**（多次运行 0.07–0.09ms） | 仅转发开销，节点为桩 |
| 整轮耗时（P50） | **≈230ms**（多次运行 227–233ms） | 15 节点 × 5ms 桩 + 状态累积 |
| 每轮事件数 | **31** | 15 `stage` + 15 `stage_summary` + 1 `result` |
| 顺序不变量违反 | **0** | 同节点 stage 先于 summary；result 唯一且在最后 |
| HTTP 层帧结构 | **8 事件，正常** | `TestClient` 打 `/api/plan/stream`：`run → stage/summary ×3 → result` |

两点必须说清楚：

1. **TTFE 不是线上首字延迟**。节点被换成 5ms 桩，这个数字只包含事件转发与状态累积开销。
2. `TestClient` 会缓冲整个响应，因此 HTTP 层只能验帧形状与事件序列，**测不到** TTFE；
   TTFE 由进程内 `run_once` 测量。两者互补，不混用。

### 顺带发现的可观测缺口

`main_meal_output` 在 `build_graph` 中存在，但 `_NODE_LABELS` 没有对应文案，
`run_stream` 会整节点过滤——用户永远看不到该阶段进度。
已在 `sse_timing.UNLABELLED_GRAPH_NODES` 固化，并有测试守护；本轮未改产品文案。

## 3. 缓存可观测

| 项 | 值 |
|---|---|
| 新指标 | `travelmind_cache_hits_total{result="hit\|miss\|disabled\|error"}` |
| 接线位置 | `app/core/cache.py:get_cached` 的返回值分支（只读计数） |
| 行为影响 | 无：key、TTL、降级路径全部未改 |
| 验证 | `tests/test_cache_metrics.py`（fake redis + `TestClient` 打 `/api/metrics`） |

**不代表生产命中率**：本机未配置 `REDIS_URL`，真实路径只会走 `disabled` 分支。
单元测试证明的是“计数与暴露链路正确”，不是“缓存有效”。

## 4. 语义记忆

`tests/test_semantic_memory.py` 覆盖 6 个行为：

- `SEMANTIC_MEMORY_ENABLED=0` → 不建集合，检索返回空；
- 空输入 → `skipped`，不误报 `degraded`；
- 不同 `user_id` 不串味（`where={"user_id": ...}` 下推）；
- 同事实去重且最多保留 3 条；
- `_memory_id` 对同一用户稳定、跨用户不同；
- 向量库异常 → `degraded`，不抛错阻塞规划。

## 5. 可写与不可写

- 可写：`pytest 178 passed（基线 134 + 新增 44），0 网络`。
- 可写：`SSE 转发层 31 事件/轮、顺序不变量 0 违反、TTFE P50 ≈0.1ms（桩节点）`。
- 可写：`/api/metrics 新增缓存结果计数，命中与否可查询而非推测`。
- 不可写：`线上首字延迟 0.1ms`。
- 不可写：`缓存命中率 X%`（本机无 Redis）。
- 不可写：`501 项测试`（实测 178）。

## 6. 复现

```powershell
..\.venv\Scripts\python.exe -m pytest -q tests
..\.venv\Scripts\python.exe -m tests.eval.sse_timing --out evaluation/benchmarks/sse
```
