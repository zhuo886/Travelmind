"""Trial runner：按冻结口径批量运行固定 fixture，并落盘可复现的 trial 记录。

用法（真实调用必须显式放行）：

    python -m tests.eval.run_trials --dry-run
    python -m tests.eval.run_trials --case nanjing-3d-sunny-history \\
        --mode planner_only --allow-external-calls

产物目录默认 ``evaluation/trials/<timestamp>/``：
- ``trial_<case>__<mode>__<k>.json``：单次运行记录
- ``summary.json`` / ``REPORT.md``：聚合结果
- ``manifest.json``：模型、时间、案例与模式
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.env import load_local_env
from app.core.llm_usage import snapshot as usage_snapshot, usage_delta
from app.planning.helpers import poi_name_matches, unknown_spots

from tests.eval.assets import validate_version, version_manifest
from tests.eval.expectations import evaluate_expectations
from tests.eval.harness import (
    EVALUATION_MODES,
    first_draft_snapshot,
    load_cases,
    run_evaluation_loop,
)
from tests.eval.metrics import aggregate, classify_trial, render_markdown

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "evaluation" / "trials"


def _route_spots(route: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [spot for day in route for spot in (day.get("spots") or [])]


def _llm_config_snapshot() -> dict[str, Any]:
    """记录本次运行生效的 LLM 开关。

    思考链开关只存在于环境变量里，事后无法从 trial 反推；不写进产物就会
    出现“这批到底开没开思考链”不可复现的问题（2026-11-08 的思考链 A/B 即为此）。
    """
    from app.planning.nodes import planner_thinking_enabled

    load_local_env()
    return {
        "model": os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL"),
        "provider": os.getenv("LLM_PROVIDER"),
        "thinking_global": (os.getenv("OPENAI_THINKING") or "").strip().lower() or None,
        "thinking_planner": planner_thinking_enabled(),
        "max_tokens": os.getenv("OPENAI_MAX_TOKENS") or None,
        "structured_method": (os.getenv("OPENAI_STRUCTURED_METHOD") or "").strip().lower() or None,
    }


def _route_digest(route: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按天记录最终交付路线，供人工离线复核；不参与任何判定口径。"""
    days: list[dict[str, Any]] = []
    for index, day in enumerate(route):
        spots = [
            {
                "name": spot.get("name"),
                "period": spot.get("period"),
                "start": spot.get("start_time"),
                "end": spot.get("end_time"),
            }
            for spot in (day.get("spots") or [])
        ]
        days.append({"day": int(day.get("day") or index + 1), "spots": spots})
    return days


def _route_signature(route: list[dict[str, Any]]) -> str:
    payload = json.dumps(route, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _snapshot_trace(
    state: Any,
    chosen: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """记录每轮快照的审核决定与返工信号，供 Reviewer 可靠性离线分析。"""
    chosen_route = (chosen or {}).get("plan", {}).get("route") or []
    chosen_signature = _route_signature(chosen_route)
    chosen_iteration = (chosen or {}).get("iteration")
    trace: list[dict[str, Any]] = []
    for snapshot in sorted(
        (state.route_history or []), key=lambda item: int(item.get("iteration", 0))
    ):
        route = (snapshot.get("plan") or {}).get("route") or []
        approved = snapshot.get("reviewer_approved")
        warnings = list(snapshot.get("reviewer_warnings") or [])
        rework_instructions = list(snapshot.get("rework_instructions") or [])
        l0 = list(snapshot.get("l0_violations") or [])
        l1 = list(snapshot.get("l1_violations") or [])
        trace.append({
            "iteration": int(snapshot.get("iteration", 0)),
            "l0_codes": [item.get("code") for item in l0],
            "l1_codes": [item.get("code") for item in l1],
            "defect_count": len(l0) + len(l1),
            "soft_score": snapshot.get("soft_score"),
            "reviewer_approved": approved,
            "reviewer_warning_count": len(warnings),
            "rework_requested": bool(rework_instructions) or (approved is False and bool(warnings)),
            "route_signature": _route_signature(route),
            "spot_names": [
                str(spot.get("name") or "")
                for day in route
                for spot in (day.get("spots") or [])
            ],
            "is_delivered": (
                chosen is not None
                and int(snapshot.get("iteration", 0)) == int(chosen_iteration or 0)
                and _route_signature(route) == chosen_signature
            ),
        })
    return trace


def _error_kind(message: str) -> str:
    text = (message or "").lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "ratelimit" in text or "429" in text or "rate limit" in text:
        return "infra"   # 账户级速率限制，不属于 Agent 规划能力
    if "amap" in text or "高德" in (message or ""):
        return "infra"
    if "clarify" in text or "缺少" in (message or ""):
        return "clarify"
    return "agent"


def _is_rate_limit(message: str) -> bool:
    text = (message or "").lower()
    return "ratelimit" in text or "429" in text or "rate limit" in text


def _must_visit_ok(route: list[dict[str, Any]], expected: list[str], destination: str | None) -> bool | None:
    if not expected:
        return None
    names = [str(spot.get("name") or "") for spot in _route_spots(route)]
    return all(
        any(poi_name_matches(name, target, destination or "") for name in names)
        for target in expected
    )


def build_trial_record(
    case: dict[str, Any],
    mode: str,
    result: dict[str, Any],
    *,
    latency_s: float,
    usage: dict[str, Any],
    error: str | None = None,
    version: str = "v1",
) -> dict[str, Any]:
    """把一次 harness 运行转换成口径要求的 trial 记录。

    v3 起区分 ``draft_generated`` 与 ``delivered_plan``：产品 FAILED 时即使
    保留着被拒绝的草稿，也不再算“生成了规划”，否则无法衡量正确拒绝。
    """
    state = result["state"]
    counts = result.get("node_counts") or {}
    benchmark = case.get("benchmark") or {}
    is_v3 = version == "v3"

    from app.planning.quality import choose_snapshot

    chosen, status, warnings, failures = choose_snapshot(state)
    first = first_draft_snapshot(state)
    route = list((chosen or {}).get("plan", {}).get("route") or [])
    draft_generated = bool(route) and int(state.days or 0) > 0
    delivered = draft_generated and str(status) != "FAILED"
    plan_generated = delivered if is_v3 else draft_generated
    delivery_route = route if plan_generated else []

    l0_codes = list((chosen or {}).get("l0_violations") or [])
    l1_codes = list((chosen or {}).get("l1_violations") or [])
    spots = _route_spots(delivery_route)

    mode_effective = str(result.get("mode_effective") or "")
    invalid_reasons: list[str] = []
    if mode_effective != mode:
        invalid_reasons.append("mode_mismatch")
    if mode == "planner_reviewer_time_check" and not counts.get("time_check"):
        invalid_reasons.append("time_check_not_executed")
    if first is None and chosen is not None:
        invalid_reasons.append("first_draft_snapshot_missing")

    record = {
        "trial_id": uuid.uuid4().hex,
        "case_id": case["id"],
        "mode_requested": mode,
        "mode_effective": mode_effective,
        "nodes_entered": sorted(counts.keys()),
        "invalid_trial": bool(invalid_reasons),
        "invalid_reason": ",".join(invalid_reasons) or None,

        "plan_generated": plan_generated,
        "status": status,
        "hard_pass": bool(plan_generated and not l0_codes),
        "l0_codes": [item.get("code") for item in l0_codes],
        "l1_codes": [item.get("code") for item in l1_codes],
        "first_draft_l0": [item.get("code") for item in ((first or {}).get("l0_violations") or [])],
        "first_draft_l1": [item.get("code") for item in ((first or {}).get("l1_violations") or [])],
        "first_draft_soft_score": (first or {}).get("soft_score"),
        "final_delivered_iteration": (chosen or {}).get("iteration"),

        "planning_revision_rounds": max(0, int(counts.get("planner", 0)) - 1),
        "review_round": int(state.review_round or 0),
        "reviewer_calls": int(counts.get("reviewer", 0)),
        "time_check_round": int(state.time_check_round or 0),
        "snapshot_count": len(state.route_history or []),
        "snapshot_trace": _snapshot_trace(state, chosen),

        "soft_score": (chosen or {}).get("soft_score") if plan_generated else None,
        "warnings": list(warnings),
        "route_names": [str(spot.get("name") or "") for spot in _route_spots(route)],
        "route_by_day": _route_digest(route),
        "delivered_route_names": [str(spot.get("name") or "") for spot in spots],
        "delivered_route_by_day": _route_digest(delivery_route),
        "oor": {"outside": len(unknown_spots(delivery_route, state.pois)), "total": len(spots)},
        "must_visit_expected": list(benchmark.get("must_visit") or []),
        "must_visit_ok": _must_visit_ok(
            delivery_route, list(benchmark.get("must_visit") or []), state.destination
        ),
        "expected_feasible": benchmark.get("expected_feasible"),
        "infeasible_reason": benchmark.get("infeasible_reason"),
        "must_avoid_ok": None,

        "latency_s": round(latency_s, 3),
        "node_latency_ms": {
            name: round(sum(values), 3)
            for name, values in (result.get("node_durations_ms") or {}).items()
            if values
        },
        "input_tokens_est": int(usage.get("input_tokens") or 0),
        "output_tokens_est": int(usage.get("output_tokens") or 0),
        "llm_calls": int(usage.get("calls_total") or 0),

        "candidate_api_calls": int(state.candidate_api_calls or 0),
        "route_leg_count": len(state.route_distance_legs or []),
        # 供 candidate_budget 复核去重与缓存命中；旧记录没有该字段，统计时按 N/A 处理。
        "candidate_search_trace": [
            {
                "action": item.get("action"),
                "query_key": item.get("query_key"),
                "error_code": item.get("error_code"),
                "cache_hit": bool(item.get("cache_hit")),
                "result_count": item.get("result_count"),
            }
            for item in (state.candidate_search_trace or [])
            if isinstance(item, dict)
        ],

        "failure_codes": [item.get("code") for item in failures],
        "error_kind": _error_kind(error) if error else None,
        "error": error,
    }
    if is_v3:
        record.update({
            "draft_generated": draft_generated,
            "delivered_plan": plan_generated,
            "draft_soft_score": (chosen or {}).get("soft_score"),
            "draft_oor": {
                "outside": len(unknown_spots(route, state.pois)),
                "total": len(_route_spots(route)),
            },
        })
        expectation = evaluate_expectations(case, record)
    else:
        expectation = {"evaluated": False, "rule": None, "violations": []}
    record["expectations_evaluated"] = bool(expectation["evaluated"])
    record["expectation_rule"] = expectation["rule"]
    record["expectation_violations"] = list(expectation["violations"])
    return classify_trial(record, benchmark)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Travelmind evaluation trial runner")
    parser.add_argument("--case", action="append", default=None, help="只跑指定 fixture id")
    parser.add_argument("--mode", action="append", default=None, choices=list(EVALUATION_MODES))
    parser.add_argument("--version", default="v1", choices=["v1", "v2", "v3"],
                        help="评测资产版本（v2 注入 must_visit；v3 新增安全负样本与交付语义）")
    parser.add_argument("--k", type=int, default=1, help="每个 case×mode 重复次数")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--allow-external-calls", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true",
                        help="产物已存在则跳过，便于长任务断点续跑")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_local_env()
    modes = args.mode or list(EVALUATION_MODES)
    asset_problems = validate_version(args.version)
    if asset_problems:
        print("评测资产校验失败：", file=sys.stderr)
        for problem in asset_problems:
            print(f"  - {problem}", file=sys.stderr)
        return 3
    cases = load_cases(args.case, version=args.version)
    if not cases:
        print("没有匹配的 fixture", file=sys.stderr)
        return 1

    plan = [(case["id"], mode, index + 1) for case in cases for mode in modes for index in range(max(1, args.k))]
    print(f"计划运行 {len(plan)} 次 trial：{len(cases)} 案例 × {len(modes)} 模式 × k={args.k}")
    if args.dry_run:
        for case_id, mode, k in plan:
            print(f"  - {case_id} / {mode} / #{k}")
        return 0
    if not args.allow_external_calls:
        print("真实运行会产生 LLM/高德调用；确认后追加 --allow-external-calls 再执行。", file=sys.stderr)
        return 2

    out_dir = args.out or DEFAULT_OUT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_config = _llm_config_snapshot()

    records: list[dict[str, Any]] = []
    for case in cases:
        for mode in modes:
            for index in range(max(1, args.k)):
                name = f"trial_{case['id']}__{mode}__{index + 1}.json"
                path = out_dir / name
                if args.skip_existing and path.exists():
                    record = json.loads(path.read_text(encoding="utf-8"))
                    records.append(record)
                    print(f"[skip] {name}")
                    continue
                before = usage_snapshot()
                started = time.perf_counter()
                error = None
                result = None
                attempts = 0
                while True:
                    try:
                        result = run_evaluation_loop(case, mode)
                        break
                    except Exception as exc:  # noqa: BLE001 - 失败也要落盘并计入分母
                        attempts += 1
                        message = f"{type(exc).__name__}: {exc}"
                        if _is_rate_limit(message) and attempts <= 3:
                            wait = 60 * attempts
                            print(f"[rate-limit] {name} 第 {attempts} 次限流，等待 {wait}s 后重试")
                            time.sleep(wait)
                            continue
                        error = message
                        result = None
                        break
                latency = time.perf_counter() - started
                usage = usage_delta(before, usage_snapshot())

                if result is None:
                    record = classify_trial({
                        "trial_id": uuid.uuid4().hex,
                        "case_id": case["id"],
                        "mode_requested": mode,
                        "mode_effective": "none",
                        "nodes_entered": [],
                        "invalid_trial": False,
                        "invalid_reason": None,
                        "plan_generated": False,
                        "status": "FAILED",
                        "hard_pass": False,
                        "l0_codes": [], "l1_codes": [], "first_draft_l0": [],
                        "final_delivered_iteration": None,
                        "planning_revision_rounds": 0,
                        "review_round": 0, "time_check_round": 0, "snapshot_count": 0,
                        "soft_score": None,
                        "oor": {"outside": 0, "total": 0},
                        "must_visit_expected": list((case.get("benchmark") or {}).get("must_visit") or []),
                        "must_visit_ok": False if (case.get("benchmark") or {}).get("must_visit") else None,
                        "expected_feasible": (case.get("benchmark") or {}).get("expected_feasible"),
                        "infeasible_reason": (case.get("benchmark") or {}).get("infeasible_reason"),
                        "must_avoid_ok": None,
                        "latency_s": round(latency, 3),
                        "node_latency_ms": {},
                        "input_tokens_est": int(usage.get("input_tokens") or 0),
                        "output_tokens_est": int(usage.get("output_tokens") or 0),
                        "llm_calls": int(usage.get("calls_total") or 0),
                        "candidate_api_calls": 0, "route_leg_count": 0,
                        "failure_codes": [],
                        "error_kind": _error_kind(error or ""),
                        "error": error,
                    }, case.get("benchmark") or {})
                else:
                    record = build_trial_record(
                        case, mode, result, latency_s=latency, usage=usage,
                        version=args.version,
                    )

                record["llm_config"] = llm_config
                path.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                records.append(record)
                print(
                    f"[{len(records)}/{len(plan)}] {case['id']} / {mode} "
                    f"-> {record['actual_outcome']} ({record['benchmark_label']}) "
                    f"{record['latency_s']}s"
                )

    summary = aggregate(records)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eval_version": args.version,
        "trial_schema_version": "v3" if args.version == "v3" else args.version,
        "model": os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL"),
        "provider": os.getenv("LLM_PROVIDER"),
        "modes": modes,
        "cases": [case["id"] for case in cases],
        "k": max(1, args.k),
        "trials": len(records),
        "llm_config": llm_config,
        "asset_manifest": version_manifest(args.version),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"产物目录：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
