"""评测 harness 的离线回归：模式强制、snapshot 纯记录、快照可读取。"""

from __future__ import annotations

from app.planning.nodes import record_route_snapshot_node
from app.planning.schemas import TravelPlanState

from tests.eval import harness

POIS = [{
    "name": "玄武湖景区",
    "rating": 4.8,
    "open_time": "周一至周日 00:00-24:00",
    "location": {"lat": 32.069455, "lng": 118.812688},
    "indoor": False,
}]

FIXTURE = {
    "id": "stub-case",
    "destination": "南京",
    "query": "南京一日游",
    "travel_start_date": "2026-08-01",
    "travel_end_date": "2026-08-01",
    "days": 1,
    "max_per_day": 2,
    "max_review_rounds": 2,
    "pois": POIS,
    "weather_forecast": [],
}


def _planner(_state: TravelPlanState) -> dict:
    return {"route": [{
        "day": 1,
        "spots": [{"name": "玄武湖景区", "start_time": "09:00", "end_time": "11:00"}],
    }]}


def _reviewer(_state: TravelPlanState) -> dict:
    return {"approved": True, "reviewer_issues": []}


def _time_check(state: TravelPlanState) -> dict:
    return {
        "time_violations": [],
        "time_check_round": int(state.time_check_round or 0) + 1,
        "time_check_done": True,
    }


def _run(mode: str) -> dict:
    return harness.run_evaluation_loop(
        FIXTURE, mode, planner=_planner, reviewer=_reviewer, time_check=_time_check,
    )


def test_planner_only_runs_one_draft_and_records_snapshot():
    result = _run("planner_only")
    counts = result["node_counts"]

    assert result["mode_effective"] == "planner_only"
    assert counts.get("planner") == 1
    assert not counts.get("reviewer")
    assert not counts.get("time_check")
    assert result["state"].route_history


def test_planner_reviewer_runs_reviewer_without_time_check():
    result = _run("planner_reviewer")
    counts = result["node_counts"]

    assert result["mode_effective"] == "planner_reviewer"
    assert counts.get("reviewer") == 1
    assert not counts.get("time_check")


def test_full_mode_forces_time_check_even_when_reviewer_approves():
    result = _run("planner_reviewer_time_check")
    counts = result["node_counts"]

    assert result["mode_effective"] == "planner_reviewer_time_check"
    assert counts.get("time_check") == 1


def test_snapshot_node_is_pure_recording():
    state = TravelPlanState(
        query="南京一日游", destination="南京", days=1, pois=POIS,
        route=[{"day": 1, "spots": [{"name": "玄武湖景区", "start_time": "09:00", "end_time": "11:00"}]}],
        review_round=1,
    )
    update = record_route_snapshot_node(state)

    assert set(update) == {"route_history", "score_info"}
    assert len(update["route_history"]) == 1
    assert update["route_history"][0]["plan"]["route"] == state.route


def test_rate_limit_is_infra_not_agent_failure():
    from tests.eval.run_trials import _error_kind, _is_rate_limit

    message = "OpenAIRateLimitError: Error code: 429 - 已达到速率限制"
    assert _is_rate_limit(message)
    assert _error_kind(message) == "infra"


def test_trial_record_carries_usage_and_snapshot_fields():
    from tests.eval.run_trials import build_trial_record

    result = _run("planner_only")
    record = build_trial_record(
        {**FIXTURE, "benchmark": {"allowed_outcomes": ["SUCCESS", "SUCCESS_WITH_WARNINGS"]}},
        "planner_only",
        result,
        latency_s=1.0,
        usage={"calls_total": 3, "input_tokens": 100, "output_tokens": 20},
    )

    assert record["llm_calls"] == 3
    assert record["input_tokens_est"] == 100
    assert record["plan_generated"] is True
    assert record["snapshot_count"] == 1
    assert record["first_draft_l0"] == []
    assert record["route_names"] == ["玄武湖景区"]
    assert record["route_by_day"][0]["spots"][0]["start"] == "09:00"
    assert isinstance(record["warnings"], list)


def test_v2_fixtures_inject_must_visit_into_query():
    from app.planning.constraints import active_must_visit

    v1 = {case["id"]: case for case in harness.load_cases(version="v1")}
    v2 = {case["id"]: case for case in harness.load_cases(version="v2")}
    case = v2["nanjing-3d-sunny-history"]

    assert case["query"] != v1["nanjing-3d-sunny-history"]["query"]
    assert active_must_visit(harness.build_state_from_fixture(case)) == ["玄武湖景区"]


def test_missing_injected_must_visit_is_l0():
    from app.planning.quality import hard_constraint_report

    case = next(
        item for item in harness.load_cases(version="v2")
        if item["id"] == "shanghai-1d-sunny-nightlife"
    )
    state = harness.build_state_from_fixture(case).model_copy(update={
        "route": [{"day": 1, "spots": [{"name": "外滩", "start_time": "18:00", "end_time": "19:00"}]}],
    })

    codes = [item["code"] for item in hard_constraint_report(state)["l0"]]

    assert "missing_must_visit" in codes


def test_first_and_final_snapshot_are_readable():
    result = _run("planner_reviewer_time_check")
    state = result["state"]

    first = harness.first_draft_snapshot(state)
    final = harness.final_delivered_snapshot(state)

    assert first is not None and first["iteration"] == 1
    assert final is not None
    assert harness.effective_mode(result["node_counts"]) == "planner_reviewer_time_check"
