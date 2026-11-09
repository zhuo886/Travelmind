"""并发通路校验基准：同一节点代码，只改变执行器宽度。

被测对象是 ``app.planning.nodes.route_distance_check_node`` 本身（不是复制一份
逻辑）：串行臂把``ThreadPoolExecutor``换成单线程池，并发臂用节点原生的
``min(8, N)`` 宽度。两者走同一个函数、同一批 job，唯一差异是并发度。

IO 等待用注入延迟模拟，因为加速比是**调度属性**：只要单次调用是纯等待，
speedup 就只取决于段数与并发度，与 120/300/600ms 的绝对值无关。这个性质
本身作为仿真正确性自检（三档延迟下 speedup 应基本一致）。

真实单次耗时用 ``--sample-external`` 单独采样，只作量级参照，不参与加速比。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor as _RealPool
from datetime import date
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from app.planning.nodes import route_distance_check_node
from app.planning.schemas import TravelPlanState

DEFAULT_OUT = Path("evaluation/benchmarks/route_parallel")
DEFAULT_LEG_COUNTS = (4, 8, 12, 16, 24, 32)
DEFAULT_DELAYS_MS = (120, 300, 600)
DEFAULT_REPEATS = 5
NODE_MAX_WORKERS = 8  # route_distance_check_node 的内置上限


# ─── 输入构造 ──────────────────────────────────────────────

def build_state(legs: int) -> TravelPlanState:
    """一天内 legs+1 个景点，正好产生 legs 段路距核验 job。"""
    spots: list[dict[str, Any]] = []
    pois: list[dict[str, Any]] = []
    for index in range(legs + 1):
        name = f"点位{index}"
        location = {"lng": 118.7 + index * 0.01, "lat": 32.0 + index * 0.01}
        spots.append({
            "name": name,
            "start_time": f"{9 + index // 2:02d}:{(index % 2) * 30:02d}",
            "end_time": f"{9 + index // 2:02d}:{(index % 2) * 30 + 20:02d}",
        })
        pois.append({"name": name, "location": location})
    return TravelPlanState(
        query="离线路距核验基准",
        destination="南京",
        travel_start_date=date(2026, 8, 1),
        travel_end_date=date(2026, 8, 1),
        days=1,
        pois=pois,
        route=[{"day": 1, "spots": spots}],
    )


def _make_stub(delay_ms: float) -> Callable[..., dict[str, Any]]:
    def stub(origin, destination, api_key, *, mode="drive", **_: Any) -> dict[str, Any]:
        time.sleep(delay_ms / 1000.0)
        return {"mode": mode, "distance_km": 1.2, "duration_min": 5, "source": "simulated"}

    return stub


def _serial_pool(max_workers: int | None = None, thread_name_prefix: str = "") -> Any:
    """把节点的执行器换成单线程池，其余实现完全不变。"""
    return _RealPool(max_workers=1, thread_name_prefix=thread_name_prefix)


# ─── 单次测量 ──────────────────────────────────────────────

def run_once(legs: int, delay_ms: float, *, serial: bool) -> dict[str, Any]:
    state = build_state(legs)
    patches = [
        patch("app.planning.nodes.amap_key", lambda: "offline-benchmark"),
        patch("app.planning.nodes.plan_route_distance", _make_stub(delay_ms)),
    ]
    if serial:
        patches.append(patch("app.planning.nodes.ThreadPoolExecutor", _serial_pool))
    started = time.perf_counter()
    for item in patches:
        item.start()
    try:
        update = route_distance_check_node(state)
    finally:
        for item in reversed(patches):
            item.stop()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {"elapsed_ms": elapsed_ms, "verified_legs": len(update.get("route_distance_legs") or [])}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def measure(legs: int, delay_ms: float, repeats: int) -> dict[str, Any]:
    parallel = [run_once(legs, delay_ms, serial=False)["elapsed_ms"] for _ in range(repeats)]
    serial = [run_once(legs, delay_ms, serial=True)["elapsed_ms"] for _ in range(repeats)]
    serial_p50 = statistics.median(serial)
    parallel_p50 = statistics.median(parallel)
    return {
        "legs": legs,
        "delay_ms": delay_ms,
        "repeats": repeats,
        "serial_p50_ms": round(serial_p50, 1),
        "serial_p95_ms": round(_percentile(serial, 0.95), 1),
        "parallel_p50_ms": round(parallel_p50, 1),
        "parallel_p95_ms": round(_percentile(parallel, 0.95), 1),
        "speedup": round(serial_p50 / parallel_p50, 3) if parallel_p50 else None,
        "effective_workers": round(serial_p50 / parallel_p50, 2) if parallel_p50 else None,
        "max_workers": min(NODE_MAX_WORKERS, legs),
        "verified_legs": parallel and run_once(legs, delay_ms, serial=False)["verified_legs"],
    }


# ─── 真实采样（可选，无 LLM Token）────────────────────────────

def sample_external(legs: int = 12) -> dict[str, Any]:
    """用真实高德方向接口采样单次耗时；仅作量级参照。"""
    from app.planning.helpers import amap_key
    from app.providers.amap.direction import plan_route_distance

    state = build_state(max(1, legs))
    locations = [spot["name"] for spot in state.route[0]["spots"]]
    poi_index = {poi["name"]: poi["location"] for poi in state.pois}
    key = amap_key()
    samples: list[float] = []
    failures = 0
    for left, right in zip(locations, locations[1:]):
        started = time.perf_counter()
        try:
            plan_route_distance(poi_index[left], poi_index[right], key, mode="drive")
        except Exception:  # noqa: BLE001 - 采样失败不阻塞基准
            failures += 1
            continue
        samples.append(round((time.perf_counter() - started) * 1000, 1))
    return {
        "requested": max(0, len(locations) - 1),
        "succeeded": len(samples),
        "failures": failures,
        "p50_ms": round(statistics.median(samples), 1) if samples else None,
        "min_ms": min(samples) if samples else None,
        "max_ms": max(samples) if samples else None,
        "samples": samples,
        "note": "真实单次耗时仅作延迟量级参照，不参与加速比计算",
    }


# ─── 报告 ──────────────────────────────────────────────────

def self_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """同段数、不同注入延迟的 speedup 应基本一致，否则说明串并行不同构。"""
    by_legs: dict[int, list[float]] = {}
    for row in rows:
        if row["speedup"] is not None:
            by_legs.setdefault(row["legs"], []).append(row["speedup"])
    spread = {
        str(legs): round(max(values) - min(values), 3)
        for legs, values in sorted(by_legs.items())
        if values
    }
    worst = max(spread.values()) if spread else None
    return {"speedup_spread_by_legs": spread, "max_spread": worst, "passed": bool(worst is not None and worst <= 0.35)}


def render_markdown(summary: dict[str, Any]) -> str:
    rows = summary["matrix"]
    check = summary["self_check"]
    best = max(
        (row for row in rows if row["speedup"] is not None),
        key=lambda row: row["speedup"],
    )
    lines = [
        "# 并发通路校验基准（IO 等待仿真）",
        "",
        "> 被测对象：`app.planning.nodes.route_distance_check_node`（生产代码，未复制逻辑）",
        "> 对照：同批 job，串行（单线程执行器）vs 节点原生并发（`min(8, N)`）",
        "> 口径：注入延迟模拟 IO 等待；**加速比是调度属性**，与延迟绝对值无关",
        "",
        "## 1. 结论",
        "",
        f"- 最大加速：N={best['legs']}、注入 {best['delay_ms']}ms 时 P50 "
        f"{best['serial_p50_ms']}ms → {best['parallel_p50_ms']}ms（**×{best['speedup']}**）",
        f"- 仿真自检：同段数不同延迟下 speedup 极差 {check['max_spread']}，"
        f"{'通过' if check['passed'] else '未通过（需检查串并行是否同构）'}",
        f"- 并发上限：节点内置 `min(8, N)`，因此 N≥8 时理论加速上界为 8",
        "",
        "## 2. 全矩阵",
        "",
        "| N 段 | 注入延迟 | 串行 P50 | 串行 P95 | 并发 P50 | 并发 P95 | 加速比 | 有效并发 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['legs']} | {row['delay_ms']}ms | {row['serial_p50_ms']}ms | "
            f"{row['serial_p95_ms']}ms | {row['parallel_p50_ms']}ms | {row['parallel_p95_ms']}ms | "
            f"×{row['speedup']} | {row['effective_workers']} |"
        )
    sample = summary.get("external_sample")
    lines += ["", "## 3. 真实单次调用耗时（参照，不参与加速比）", ""]
    if sample and sample.get("succeeded"):
        lines += [
            f"- 采样 {sample['succeeded']}/{sample['requested']} 次成功，失败 {sample['failures']}",
            f"- 单次耗时 P50 {sample['p50_ms']}ms，范围 {sample['min_ms']}~{sample['max_ms']}ms",
            "- 用法：把该量级代回矩阵即可估线上收益；它不是线上 P95。",
        ]
    else:
        lines.append("- 未执行真实采样（`--sample-external` 未开启或全部失败）")
    lines += [
        "",
        "## 4. 不可写与边界",
        "",
        "- 不可写“线上路距核验 P50 降低 X 倍”：本轮是调度仿真，不是线上观测。",
        "- 串行臂仍是同一节点代码，只是执行器宽度为 1；不存在“另写一个慢实现”的对照偏差。",
        "- 若 N < 8，加速比上限是 N；报告请同时给出 N 与并发度，避免用大 N 掩盖小场景收益。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="并发通路校验基准（离线）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--legs", type=int, nargs="*", default=list(DEFAULT_LEG_COUNTS))
    parser.add_argument("--delays", type=int, nargs="*", default=list(DEFAULT_DELAYS_MS))
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--sample-external", action="store_true",
                        help="额外采样真实高德方向接口耗时（无 LLM Token）")
    args = parser.parse_args(argv)

    rows = [
        measure(legs, delay, args.repeats)
        for delay in args.delays
        for legs in args.legs
    ]
    summary: dict[str, Any] = {
        "benchmark": "route_parallel_validation",
        "kind": "io_wait_simulation",
        "node": "app.planning.nodes.route_distance_check_node",
        "node_max_workers": NODE_MAX_WORKERS,
        "matrix": rows,
        "self_check": self_check(rows),
    }
    if args.sample_external:
        summary["external_sample"] = sample_external()
    else:
        summary["external_sample"] = None

    args.out.mkdir(parents=True, exist_ok=True)
    if summary["external_sample"] is not None:
        # 真实采样单独落盘，便于复核单次耗时分布
        (args.out / "samples.json").write_text(
            json.dumps(summary["external_sample"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    best = max((row for row in rows if row["speedup"]), key=lambda row: row["speedup"])
    print(f"matrix={len(rows)} rows; best=N{best['legs']} ×{best['speedup']} "
          f"({best['serial_p50_ms']}ms → {best['parallel_p50_ms']}ms)")
    print(f"self-check passed={summary['self_check']['passed']} "
          f"max_spread={summary['self_check']['max_spread']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
