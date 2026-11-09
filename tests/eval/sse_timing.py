"""SSE 流式时序基准（本地桩，0 网络）。

测的是 ``app.planning.graph.run_stream`` 的**事件转发层**：
从调用开始到第一条 ``stage`` 事件的时间（TTFE）、完整一轮的事件数、
以及"每个阶段的 stage 必先于其 stage_summary"这类顺序不变量。

节点本身被替换成固定延迟的桩，因此这里得到的是**框架开销**，
不是线上真实首字延迟。真实节点耗时见各 trial 的 ``node_latency_ms``。

用法::

    python -m tests.eval.sse_timing --out evaluation/benchmarks/sse
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

import app.planning.graph as graph_module

DEFAULT_OUT = Path("evaluation/benchmarks/sse")
# 生产图里的节点顺序（只含已挂进度文案的节点）。
# main_meal_output 在 build_graph 中存在但 _NODE_LABELS 没有文案，
# run_stream 会直接过滤掉它，因此它永远不会出现在 SSE 里——这是一个真实的
# 可观测缺口，单独记录而不是默默从序列里删掉。
CANONICAL_SEQUENCE = (
    "intent", "query_rewrite", "weather_search", "attraction_search",
    "candidate_react", "candidate_search", "candidate_validator",
    "main_meal_search", "planner", "route_distance_check", "risk_gate",
    "reviewer", "time_check", "spot_tips", "finalize",
)
UNLABELLED_GRAPH_NODES = ("main_meal_output",)


def _event(kind: str, name: str, output: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"event": kind, "name": name, "data": {} if output is None else {"output": output}}


class _TimedGraph:
    def __init__(self, delay_ms: float, sequence: tuple[str, ...]) -> None:
        self.delay_ms = delay_ms
        self.sequence = sequence

    async def astream_events(self, _state: Any, config: Any = None, version: str = "v2"):
        for node in self.sequence:
            yield _event("on_chain_start", node)
            await asyncio.sleep(self.delay_ms / 1000.0)
            yield _event("on_chain_end", node, {"final_plan": {"days": []}} if node.startswith("finalize") else {})


def run_once(delay_ms: float, sequence: tuple[str, ...] = CANONICAL_SEQUENCE) -> dict[str, Any]:
    async def collect() -> dict[str, Any]:
        started = time.perf_counter()
        first_stage_ms: float | None = None
        events: list[dict[str, Any]] = []
        async for event in graph_module.run_stream("时序基准：南京一日"):
            if first_stage_ms is None and event.get("type") == "stage":
                first_stage_ms = (time.perf_counter() - started) * 1000
            events.append(event)
        total_ms = (time.perf_counter() - started) * 1000
        return {
            "ttfe_ms": round(first_stage_ms or 0, 2),
            # Spec 里的字段名，与 ttfe_ms 同值，便于跨文档检索
            "time_to_first_event_ms": round(first_stage_ms or 0, 2),
            "total_ms": round(total_ms, 2),
            "events": events,
        }

    with_delay = _TimedGraph(delay_ms, sequence)
    original = graph_module.build_graph
    graph_module.build_graph = lambda *a, **k: with_delay
    try:
        result = asyncio.run(collect())
    finally:
        graph_module.build_graph = original

    events = result.pop("events")
    stages = [event["node"] for event in events if event.get("type") == "stage"]
    summaries = [event["node"] for event in events if event.get("type") == "stage_summary"]
    results = [event for event in events if event.get("type") == "result"]
    violations: list[str] = []
    for node in stages:
        if node not in graph_module._NODE_LABELS:
            violations.append(f"unlabeled:{node}")
    for node in summaries:
        first_stage = stages.index(node) if node in stages else None
        first_summary = summaries.index(node)
        if first_stage is None or first_stage > first_summary:
            violations.append(f"order:{node}")
    if len(results) != 1:
        violations.append(f"result_count:{len(results)}")
    if events and events[-1].get("type") != "result":
        violations.append("result_not_last")

    return {
        **result,
        "stages": len(stages),
        "summaries": len(summaries),
        "result_events": len(results),
        "violations": violations,
        "sequence_respected": stages == list(sequence),
    }


def http_probe(delay_ms: float = 0.0) -> dict[str, Any]:
    """用 TestClient 走真实 SSE 端点，验证帧形状与事件序列。

    ``TestClient`` 会缓冲整个响应，所以拿不到真实的“首事件”时间；
    TTFE 必须在进程内量（``run_once``）。这里只证明 HTTP 层的帧没有被破坏。
    """
    import os

    from fastapi.testclient import TestClient

    import app.main as main
    from app.core.auth import create_token

    async def fake_stream(*_args: Any, **_kwargs: Any):
        for node in ("intent", "planner", "finalize"):
            yield {"type": "stage", "node": node, "label": "probe"}
            await asyncio.sleep(delay_ms / 1000.0)
            yield {"type": "stage_summary", "node": node, "summary": "ok"}
        yield {"type": "result", "success": True, "missing_fields": [], "history": [], "plan": None}

    previous_secret = os.environ.get("JWT_SECRET")
    os.environ.setdefault("JWT_SECRET", "test-only-secret-with-sufficient-length")
    original = main.run_plan_stream
    main.run_plan_stream = fake_stream
    try:
        client = TestClient(main.app)
        headers = {"Authorization": "Bearer " + create_token("sse-probe")}
        started = time.perf_counter()
        response = client.post("/api/plan/stream", json={"query": "南京一日"}, headers=headers)
        total_ms = (time.perf_counter() - started) * 1000
    finally:
        main.run_plan_stream = original
        if previous_secret is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = previous_secret

    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [event.get("type") for event in events]
    return {
        "status_code": response.status_code,
        "events": len(events),
        "event_types": types,
        "result_unique": types.count("result") == 1,
        "result_last": bool(types) and types[-1] == "result",
        "total_ms": round(total_ms, 1),
        "note": "TestClient 缓冲整个响应，TTFE 只能在进程内测；此处验帧形状与事件序列",
    }


def build_summary(repeats: int = 5, delay_ms: float = 5.0) -> dict[str, Any]:
    runs = [run_once(delay_ms) for _ in range(repeats)]
    ttfe = [run["ttfe_ms"] for run in runs]
    total = [run["total_ms"] for run in runs]
    return {
        "benchmark": "sse_timing",
        "kind": "local_stub",
        "node_delay_ms": delay_ms,
        "repeats": repeats,
        "nodes": len(CANONICAL_SEQUENCE),
        "ttfe_p50_ms": round(statistics.median(ttfe), 2),
        "time_to_first_event_p50_ms": round(statistics.median(ttfe), 2),
        "ttfe_min_ms": round(min(ttfe), 2),
        "total_p50_ms": round(statistics.median(total), 2),
        "events_per_run": runs[0]["stages"] * 2 + 1,
        "violations": sorted({item for run in runs for item in run["violations"]}),
        "order_compliance": round(
            sum(1 for run in runs if not run["violations"]) / len(runs), 4
        ),
        "sequence_respected": all(run["sequence_respected"] for run in runs),
        "unlabeled_graph_nodes": list(UNLABELLED_GRAPH_NODES),
        "http_probe": http_probe(),
        "runs": [{k: v for k, v in run.items() if k != "violations"} for run in runs],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    return "\n".join([
        "# SSE 流式时序基准（本地桩）",
        "",
        "> 被测对象：`app.planning.graph.run_stream` 的事件转发层",
        f"> 桩节点延迟：{summary['node_delay_ms']}ms × {summary['nodes']} 个节点，重复 {summary['repeats']} 次",
        "",
        "## 1. 结果",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| 首事件延迟 TTFE（P50） | {summary['ttfe_p50_ms']}ms |",
        f"| 首事件延迟（最小） | {summary['ttfe_min_ms']}ms |",
        f"| 整轮耗时（P50） | {summary['total_p50_ms']}ms |",
        f"| 每轮事件数 | {summary['events_per_run']}（{summary['nodes']} stage + {summary['nodes']} summary + 1 result） |",
        f"| 顺序不变量违反 | {summary['violations'] or '无'} |",
        f"| 合规轮次 | {summary['order_compliance'] * 100:.1f}% |",
        f"| 图上存在但无进度文案的节点 | {summary['unlabeled_graph_nodes']} |",
        f"| HTTP 层事件数 / 帧结构 | {summary['http_probe']['events']} / "
        f"{'正常' if summary['http_probe']['status_code'] == 200 else '异常'} |",
        "",
        "## 2. 读法",
        "",
        "- TTFE 只包含转发与快照开销，不含任何模型或检索耗时；不能当线上首字延迟。",
        "- 顺序不变量：每个节点的 `stage` 必须先于其 `stage_summary`，且 `result` 唯一且在最后。",
        "- `main_meal_output` 没有进度文案，`run_stream` 会把它过滤掉，因此用户看不到该阶段；"
        "这不是测试遗漏，而是已记录的可观测缺口。",
        "- 生产并行分支的到达顺序不固定，因此这里只校验“同节点先后”，不校验跨节点全序。",
        f"- HTTP 层：`{summary['http_probe']['note']}`（状态码 {summary['http_probe']['status_code']}，"
        f"事件 {summary['http_probe']['events']}，result 唯一={summary['http_probe']['result_unique']}）。",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SSE 时序基准（本地桩）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--node-delay-ms", type=float, default=5.0)
    args = parser.parse_args(argv)

    summary = build_summary(args.repeats, args.node_delay_ms)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"ttfe_p50={summary['ttfe_p50_ms']}ms total_p50={summary['total_p50_ms']}ms "
          f"violations={summary['violations'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
