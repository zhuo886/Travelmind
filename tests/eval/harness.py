"""fixture 驱动的评测 harness。

三种模式由 harness 自己强制，绕过生产图的 risk gate，保证 A/B/C 使用同一份输入：

- ``planner_only``：只跑一次 Planner 草稿
- ``planner_reviewer``：Planner ⇄ Reviewer，不进入 Time Check
- ``planner_reviewer_time_check``：Reviewer 结束后**强制**进入 Time Check
  （生产路由在 clean snapshot 时会直接 finalize，不能用于消融）

每个模式都会挂 snapshot 节点，与生产图保持同样的快照语义；snapshot 节点只记录
``route_history`` / ``score_info``，不改变路线、审批状态或路由条件。
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

from langgraph.graph import END, START, StateGraph

from app.planning.nodes import (
    make_planner_node,
    make_reviewer_node,
    make_time_check_node,
    record_route_snapshot_node,
    route_after_review,
    route_after_risk_gate,
    route_after_time_check,
    route_risk_gate_node,
)
from app.planning.quality import choose_snapshot
from app.planning.schemas import TravelPlanState

_EVAL_ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = _EVAL_ROOT / "fixtures"
BENCHMARK_FILE = _EVAL_ROOT / "benchmark_v1.json"
EVAL_ASSETS: dict[str, tuple[Path, Path]] = {
    "v1": (FIXTURES_DIR, BENCHMARK_FILE),
    "v2": (_EVAL_ROOT / "fixtures_v2", _EVAL_ROOT / "benchmark_v2.json"),
    # v3 只新增安全负样本，其余 fixture 从 v2 继承，避免复制导致 drifting。
    "v3": (_EVAL_ROOT / "fixtures_v3", _EVAL_ROOT / "benchmark_v3.json"),
}
ASSET_FALLBACK: dict[str, tuple[str, ...]] = {"v3": ("v2",)}

EvaluationMode = Literal[
    "planner_only",
    "planner_reviewer",
    "planner_reviewer_time_check",
    "planner_risk_gate",
]
# 默认三臂保持不变：新增模式不参与 run_trials 的默认矩阵，避免污染既有分母。
EVALUATION_MODES: tuple[EvaluationMode, ...] = (
    "planner_only",
    "planner_reviewer",
    "planner_reviewer_time_check",
)
# 第四臂复刻生产路由（risk gate 可能跳过审核），只在策略对照中显式使用。
POLICY_MODES: tuple[EvaluationMode, ...] = (*EVALUATION_MODES, "planner_risk_gate")

Node = Callable[[TravelPlanState], dict[str, Any]]


# ─── 数据加载 ──────────────────────────────────────────────

def _assets(version: str) -> tuple[Path, Path]:
    if version not in EVAL_ASSETS:
        raise ValueError(f"unknown eval version: {version}")
    return EVAL_ASSETS[version]


def _fixture_dirs(version: str) -> list[Path]:
    """按继承顺序返回 fixture 目录；v3 覆盖 v2 同名 case。"""
    versions = (*ASSET_FALLBACK.get(version, ()), version)
    return [EVAL_ASSETS[name][0] for name in versions]


def load_benchmark(version: str = "v1") -> dict[str, dict[str, Any]]:
    """读取 benchmark 元数据（allowed_outcomes / must_visit）。"""
    _fixtures_dir, benchmark_file = _assets(version)
    if not benchmark_file.exists():
        return {}
    data = json.loads(benchmark_file.read_text(encoding="utf-8"))
    return {item["id"]: item for item in data.get("cases", [])}


def load_cases(only: str | list[str] | None = None, version: str = "v1") -> list[dict[str, Any]]:
    """加载 fixtures，并合并 benchmark 元数据到 ``benchmark`` 字段。

    v3 先读 v2 再读 v3；同 id 以后者为准，因此只维护新增 fixture。
    """
    wanted = {only} if isinstance(only, str) else set(only or [])
    meta = load_benchmark(version)
    fixtures: dict[str, dict[str, Any]] = {}
    for fixtures_dir in _fixture_dirs(version):
        for path in sorted(fixtures_dir.glob("*.json")):
            fx = json.loads(path.read_text(encoding="utf-8"))
            fx.setdefault("id", path.stem)
            fx["fixture_dir"] = str(fixtures_dir.name)
            fixtures[fx["id"]] = fx
    cases: list[dict[str, Any]] = []
    for case_id in sorted(fixtures):
        if wanted and case_id not in wanted:
            continue
        fx = fixtures[case_id]
        fx["benchmark"] = meta.get(case_id, {})
        cases.append(fx)
    return cases


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def build_state_from_fixture(fx: dict[str, Any]) -> TravelPlanState:
    """用 fixture 冻结 planner 所需的全部输入（pois 中的 indoor 标签原样透传）。"""
    return TravelPlanState(
        query=fx.get("query") or f"{fx.get('destination', '')}{fx.get('days', '')}日游",
        destination=fx.get("destination"),
        travel_start_date=_parse_date(fx.get("travel_start_date")),
        travel_end_date=_parse_date(fx.get("travel_end_date")),
        days=int(fx.get("days", 0)),
        attraction_preference=fx.get("attraction_preference"),
        food_preference=fx.get("food_preference"),
        habit_preference=fx.get("habit_preference"),
        max_walking_km=fx.get("max_walking_km"),
        rain_indoor_priority=bool(fx.get("rain_indoor_priority", False)),
        max_duration_hours=fx.get("max_duration_hours"),
        latest_end_time=fx.get("latest_end_time"),
        max_per_day=int(fx.get("max_per_day", 3)),
        min_rating=float(fx.get("min_rating", 4.5)),
        max_spots=int(fx.get("max_spots", 30)),
        max_review_rounds=int(fx.get("max_review_rounds", 3)),
        model_name=fx.get("model_name"),
        pois=list(fx.get("pois", [])),
        weather_forecast=list(fx.get("weather_forecast", [])),
        weather_note=fx.get("weather_note"),
    )


# ─── 路由 ──────────────────────────────────────────────────

def _route_review_stop(state: TravelPlanState) -> str:
    """B 组：Reviewer 后只允许回到 Planner 或结束。"""
    return "planner" if route_after_review(state) == "planner" else "end"


def _route_review_force_time_check(state: TravelPlanState) -> str:
    """C 组：Reviewer 结束后强制进入 Time Check，不沿用生产的 clean→finalize。"""
    if route_after_review(state) == "planner":
        return "planner"
    if state.time_check_round >= state.max_time_check_rounds + state.max_review_rounds:
        return "end"
    return "time_check"


def _route_time_check_eval(state: TravelPlanState) -> str:
    """Time Check 后只保留回到 Planner 的返工路径，其余分支结束。"""
    nxt = route_after_time_check(state)
    return "planner" if isinstance(nxt, str) and nxt == "planner" else "end"


def _route_risk_gate_eval(state: TravelPlanState) -> str:
    """直接复用生产路由：审核 / 时间核验 / 直接收尾。"""
    nxt = route_after_risk_gate(state)
    if nxt == "reviewer":
        return "reviewer"
    if nxt == "time_check":
        return "time_check"
    return "end"


def _route_review_production(state: TravelPlanState) -> str:
    """生产语义：打回 planner、进入 time_check、或直接交付。"""
    nxt = route_after_review(state)
    if nxt == "planner":
        return "planner"
    return "time_check" if nxt == "time_check" else "end"


def effective_mode(counts: dict[str, int]) -> str:
    if counts.get("risk_gate"):
        return "planner_risk_gate"
    if counts.get("time_check"):
        return "planner_reviewer_time_check"
    if counts.get("reviewer"):
        return "planner_reviewer"
    return "planner_only"


# ─── 图构造 ──────────────────────────────────────────────

def _wrap(
    name: str,
    node: Node,
    counts: dict[str, int],
    durations: dict[str, list[float]],
) -> Node:
    def wrapped(state: TravelPlanState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            return node(state)
        finally:
            counts[name] = counts.get(name, 0) + 1
            durations.setdefault(name, []).append((time.perf_counter() - started) * 1000)

    return wrapped


def build_evaluation_graph(
    mode: EvaluationMode = "planner_reviewer_time_check",
    model_name: str | None = None,
    *,
    planner: Node | None = None,
    reviewer: Node | None = None,
    time_check: Node | None = None,
    counts: dict[str, int] | None = None,
    durations: dict[str, list[float]] | None = None,
):
    """按模式构造与生产节点一致的评测子图（不包含 risk gate）。"""
    if mode not in POLICY_MODES:
        raise ValueError(f"unknown evaluation mode: {mode}")
    counts = counts if counts is not None else {}
    durations = durations if durations is not None else {}

    g = StateGraph(TravelPlanState)
    g.add_node("planner", _wrap("planner", planner or make_planner_node(model_name), counts, durations))
    g.add_node("snapshot_gate", _wrap("snapshot_gate", record_route_snapshot_node, counts, durations))
    g.add_edge(START, "planner")
    g.add_edge("planner", "snapshot_gate")

    if mode == "planner_only":
        g.add_edge("snapshot_gate", END)
        return g.compile()

    g.add_node("reviewer", _wrap("reviewer", reviewer or make_reviewer_node(model_name), counts, durations))
    g.add_node("snapshot_reviewer", _wrap("snapshot_reviewer", record_route_snapshot_node, counts, durations))
    if mode == "planner_risk_gate":
        g.add_node("risk_gate", _wrap("risk_gate", route_risk_gate_node, counts, durations))
        g.add_edge("snapshot_gate", "risk_gate")
    else:
        g.add_edge("snapshot_gate", "reviewer")
    g.add_edge("reviewer", "snapshot_reviewer")

    if mode == "planner_risk_gate":
        g.add_node("time_check", _wrap("time_check", time_check or make_time_check_node(model_name), counts, durations))
        g.add_node("snapshot_time_check", _wrap("snapshot_time_check", record_route_snapshot_node, counts, durations))
        g.add_conditional_edges(
            "risk_gate", _route_risk_gate_eval,
            {"reviewer": "reviewer", "time_check": "time_check", "end": END},
        )
        g.add_conditional_edges(
            "snapshot_reviewer", _route_review_production,
            {"planner": "planner", "time_check": "time_check", "end": END},
        )
        g.add_edge("time_check", "snapshot_time_check")
        g.add_conditional_edges(
            "snapshot_time_check", _route_time_check_eval,
            {"planner": "planner", "end": END},
        )
        return g.compile()

    if mode == "planner_reviewer":
        g.add_conditional_edges(
            "snapshot_reviewer", _route_review_stop,
            {"planner": "planner", "end": END},
        )
        return g.compile()

    g.add_node("time_check", _wrap("time_check", time_check or make_time_check_node(model_name), counts, durations))
    g.add_node("snapshot_time_check", _wrap("snapshot_time_check", record_route_snapshot_node, counts, durations))
    g.add_conditional_edges(
        "snapshot_reviewer", _route_review_force_time_check,
        {"planner": "planner", "time_check": "time_check", "end": END},
    )
    g.add_edge("time_check", "snapshot_time_check")
    g.add_conditional_edges(
        "snapshot_time_check", _route_time_check_eval,
        {"planner": "planner", "end": END},
    )
    return g.compile()


def recursion_limit(state: TravelPlanState) -> int:
    return 2 * (int(state.max_review_rounds) + 1) + 2 * int(state.max_time_check_rounds) + 12


def run_evaluation_loop(
    fx: dict[str, Any],
    mode: EvaluationMode = "planner_reviewer_time_check",
    model_name: str | None = None,
    *,
    planner: Node | None = None,
    reviewer: Node | None = None,
    time_check: Node | None = None,
) -> dict[str, Any]:
    """跑一次指定模式，返回最终 state 与节点执行轨迹。"""
    state = build_state_from_fixture(fx)
    counts: dict[str, int] = {}
    durations: dict[str, list[float]] = {}
    app = build_evaluation_graph(
        mode, state.model_name or model_name,
        planner=planner, reviewer=reviewer, time_check=time_check,
        counts=counts, durations=durations,
    )
    started = time.perf_counter()
    result = app.invoke(state, config={"recursion_limit": recursion_limit(state)})
    latency_s = round(time.perf_counter() - started, 3)
    final = TravelPlanState(**result) if isinstance(result, dict) else result
    return {
        "state": final,
        "node_counts": dict(counts),
        "node_durations_ms": {name: values for name, values in durations.items()},
        "mode_requested": mode,
        "mode_effective": effective_mode(counts),
        "latency_s": latency_s,
    }


# ─── 快照读取 ──────────────────────────────────────────────

def first_draft_snapshot(state: TravelPlanState) -> dict[str, Any] | None:
    """首版 Planner 草稿：iteration 最小的一份快照。"""
    history = list(state.route_history or [])
    if not history:
        return None
    return min(history, key=lambda item: int(item.get("iteration", 0)))


def final_delivered_snapshot(state: TravelPlanState) -> dict[str, Any] | None:
    """最终交付快照：与生产 finalize 一致，取 ``choose_snapshot`` 的结果。"""
    chosen, _status, _warnings, _failures = choose_snapshot(state)
    return chosen
