"""不可行安全：下界证明、v3 交付语义、safety 聚合与 expectations。"""

from __future__ import annotations

from app.planning.nodes import record_route_snapshot_node

from tests.eval import feasibility, harness
from tests.eval.expectations import evaluate_expectations
from tests.eval.metrics import aggregate, classify_trial
from tests.eval.run_trials import build_trial_record

CASES = {case["id"]: case for case in harness.load_cases(version="v3")}
SHANGHAI = "shanghai-1d-twohour-three-must-negative"
SANYA = "sanya-1d-indooronly-empty-pool-negative"


def _record(**overrides):
    base = {
        "case_id": "case",
        "mode_requested": "planner_only",
        "plan_generated": True,
        "status": "SUCCESS",
        "hard_pass": True,
        "l0_codes": [],
        "l1_codes": [],
        "first_draft_l0": [],
        "planning_revision_rounds": 0,
        "invalid_trial": False,
        "error_kind": None,
        "failure_codes": [],
        "latency_s": 1.0,
        "soft_score": 80.0,
        "oor": {"outside": 0, "total": 10},
    }
    base.update(overrides)
    return base


def _state_with_route(case: dict, route: list[dict]) -> dict:
    state = harness.build_state_from_fixture(case)
    state = state.model_copy(update={"route": route, "review_round": 1})
    return state.model_copy(update=record_route_snapshot_node(state))


def _result(state) -> dict:
    return {
        "state": state,
        "node_counts": {"planner": 1, "snapshot_gate": 1},
        "node_durations_ms": {},
        "mode_effective": "planner_only",
    }


def test_new_safety_fixtures_are_provably_infeasible():
    verdicts = feasibility.assess_version("v3")

    shanghai = verdicts[SHANGHAI]
    assert shanghai["verdict"] == "INFEASIBLE"
    assert shanghai["reason_code"] == "physical_time_deadlock"
    assert shanghai["evidence"]["required_minutes_lower_bound"] > shanghai["evidence"]["window_minutes"]

    sanya = verdicts[SANYA]
    assert sanya["verdict"] == "INFEASIBLE"
    assert sanya["reason_code"] == "candidate_pool_preference_conflict"
    assert sanya["evidence"]["indoor_true"] == 0


def test_existing_cases_are_not_falsely_marked_infeasible():
    verdicts = feasibility.assess_version("v3")
    benchmark = harness.load_benchmark("v3")

    for case_id, case in benchmark.items():
        if case.get("expected_feasible") is True:
            assert verdicts[case_id]["verdict"] != "INFEASIBLE", case_id


def test_v3_treats_rejected_draft_as_correct_reject():
    route = [{
        "day": 1,
        "spots": [{"name": "亚龙湾海滩", "start_time": "10:00", "end_time": "12:00"}],
    }]
    case = CASES[SANYA]
    state = _state_with_route(case, route)
    record = build_trial_record(
        case, "planner_only", _result(state),
        latency_s=1.0, usage={}, version="v3",
    )

    assert record["draft_generated"] is True
    assert record["delivered_plan"] is False
    assert record["plan_generated"] is False
    assert record["actual_outcome"] == "CORRECT_REJECT"
    assert "candidate_pool_preference_conflict" in record["failure_codes"]


def test_v1_keeps_draft_semantics_for_the_same_state():
    route = [{
        "day": 1,
        "spots": [{"name": "亚龙湾海滩", "start_time": "10:00", "end_time": "12:00"}],
    }]
    case = CASES[SANYA]
    state = _state_with_route(case, route)
    record = build_trial_record(
        case, "planner_only", _result(state),
        latency_s=1.0, usage={}, version="v1",
    )

    assert record["plan_generated"] is True
    assert record["actual_outcome"] == "HARD_FAIL"
    assert "delivered_plan" not in record


def test_expectations_flags_outdoor_spots_on_bad_day():
    record = {
        "plan_generated": True,
        "route_by_day": [{
            "day": 1,
            "spots": [{"name": "亚龙湾海滩"}, {"name": "天涯海角游览区"}],
        }],
    }
    result = evaluate_expectations(CASES[SANYA], record)

    assert result["evaluated"] is True
    assert len(result["violations"]) == 1
    assert result["violations"][0]["outdoor_count"] == 2


def test_expectations_ignores_indoor_spots():
    case = {
        **CASES[SANYA],
        "pois": [{"name": "室内展馆", "indoor": True}],
    }
    record = {
        "plan_generated": True,
        "route_by_day": [{"day": 1, "spots": [{"name": "室内展馆"}]}],
    }
    result = evaluate_expectations(case, record)

    assert result["evaluated"] is True
    assert result["violations"] == []


def test_safety_metrics_split_correct_reject_partial_and_wrong_accept():
    bench_infeasible = {
        "allowed_outcomes": ["CORRECT_REJECT", "PARTIAL"],
        "expected_feasible": False,
    }
    bench_success = {"allowed_outcomes": ["SUCCESS", "SUCCESS_WITH_WARNINGS"], "expected_feasible": True}
    records = [
        classify_trial(_record(
            plan_generated=False, status="FAILED", hard_pass=False,
            failure_codes=["candidate_pool_preference_conflict"], expected_feasible=False,
        ), bench_infeasible),
        classify_trial(_record(
            plan_generated=True, status="PARTIAL_SUCCESS", expected_feasible=False,
        ), bench_infeasible),
        classify_trial(_record(
            plan_generated=True, status="SUCCESS", expected_feasible=False,
        ), bench_infeasible),
        classify_trial(_record(
            plan_generated=False, status="FAILED", hard_pass=False, expected_feasible=True,
        ), bench_success),
    ]
    safety = aggregate(records)["safety"]

    assert safety["infeasible_trials"] == 3
    assert safety["correct_reject"] == 1
    assert safety["partial"] == 1
    assert safety["wrong_accept"] == 1
    assert safety["srr"] == {"num": 1, "den": 3, "value": 0.3333}
    assert safety["war"] == {"num": 1, "den": 3, "value": 0.3333}
    assert safety["partial_delivery_rate"] == {"num": 1, "den": 3, "value": 0.3333}
    assert safety["non_reject_delivery_rate"] == {"num": 2, "den": 3, "value": 0.6667}
    assert safety["feasible_trials"] == 1
    assert safety["over_reject"] == 1
    assert safety["orr"]["value"] == 1.0


def test_safety_is_absent_without_expected_feasible_labels():
    summary = aggregate([classify_trial(_record(), {"allowed_outcomes": ["SUCCESS"]})])

    assert summary["safety"] is None
    assert summary["denominator_basis"] == "plan_generated"