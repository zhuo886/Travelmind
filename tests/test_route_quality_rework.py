from datetime import date

from app.planning.candidate_react import candidate_validator_node, route_after_candidate_validation
from app.planning.nodes import route_after_review
from app.planning.quality import choose_snapshot, hard_constraint_report, result_envelope, terminal_infeasibility
from app.planning.schemas import TravelPlanState


def snapshot(iteration, score, *, l0=None, l1=None):
    return {
        "iteration": iteration,
        "plan": {"route": [{"day": 1, "spots": [{"name": f"POI-{iteration}"}]}], "meal_slots": []},
        "l0_violations": l0 or [],
        "l1_violations": l1 or [],
        "soft_score": score,
        "score_breakdown": {"named_poi": score},
        "reviewer_approved": not bool(l0 or l1),
        "reviewer_warnings": [],
        "rework_instructions": [],
    }


def test_candidate_pool_checker_relaxes_count_after_bounded_search():
    state = TravelPlanState(
        query="南京一日游", destination="南京", days=1,
        pois=[{"name": "博物馆", "location": {"lat": 32.0, "lng": 118.0}}],
        candidate_search_round=2,
        candidate_search_actions=[{"action": "stop"}],
    )
    update = candidate_validator_node(state)
    assert update["candidate_pool_status"] == "insufficient"
    assert update["relaxed_constraints"]["relaxed_count"] is True
    assert route_after_candidate_validation(state.model_copy(update=update)) == "planner"


def test_unique_missing_candidate_short_circuits_with_failure_reason():
    state = TravelPlanState(
        query="南京去‘不存在景点’", destination="南京", days=1,
        candidate_search_round=2,
        candidate_search_actions=[{"action": "stop"}],
        candidate_search_trace=[{"query": "不存在景点", "query_key": "q", "error_code": "EMPTY"}],
    )
    update = candidate_validator_node(state)
    assert update["candidate_pool_status"] == "failed"
    assert update["relaxed_constraints"]["failure_reasons"]
    assert route_after_candidate_validation(state.model_copy(update=update)) == "candidate_failure"


def test_history_tier_one_chooses_highest_score_and_latest_tie():
    state = TravelPlanState(query="x", route_history=[
        snapshot(1, 0, l1=[{"code": "opening_time_conflict", "message": "时间冲突"}]),
        snapshot(2, 78), snapshot(3, 88), snapshot(4, 80),
    ])
    chosen, status, warnings, failures = choose_snapshot(state)
    assert chosen["iteration"] == 3
    assert status == "SUCCESS"
    assert not warnings and not failures


def test_history_tier_two_prefers_fewer_l1_defects_over_score():
    state = TravelPlanState(query="x", route_history=[
        snapshot(1, 95, l1=[{"code": "walking_constraint", "message": "步行超限"}, {"code": "commute_time_conflict", "message": "通勤不足"}]),
        snapshot(2, 70, l1=[{"code": "walking_constraint", "message": "步行超限"}]),
        snapshot(3, 88, l1=[{"code": "walking_constraint", "message": "步行超限"}]),
    ])
    chosen, status, warnings, failures = choose_snapshot(state)
    assert chosen["iteration"] == 3
    assert status == "PARTIAL_SUCCESS"
    assert "步行超限" in warnings
    assert not failures


def test_all_l0_versions_return_structured_failure():
    state = TravelPlanState(query="x", route_history=[
        snapshot(1, 80, l0=[{"code": "unknown_poi", "message": "候选池外景点"}]),
        snapshot(2, 75, l0=[{"code": "missing_must_visit", "message": "缺少点名景点"}]),
        snapshot(3, 70, l0=[{"code": "route_structure", "message": "路线结构不完整"}]),
    ])
    chosen, status, warnings, failures = choose_snapshot(state)
    assert chosen["iteration"] == 3
    assert status == "FAILED"
    assert failures[0]["stage"] == "L0_CONSTRAINT"
    assert not warnings


def _weather_state(**overrides):
    base = dict(
        query="三亚三天全程雨", destination="三亚", days=1,
        travel_start_date=date(2026, 10, 15), travel_end_date=date(2026, 10, 15),
        max_per_day=3,
        pois=[{"name": "海滩A", "indoor": False}, {"name": "海滩B", "indoor": False}],
        weather_forecast=[{"date": "2026-10-15", "is_bad": True}],
        route=[{"day": 1, "spots": [
            {"name": "海滩A", "start_time": "10:00", "end_time": "12:00"},
            {"name": "海滩B", "start_time": "14:00", "end_time": "16:00"},
        ]}],
    )
    base.update(overrides)
    return TravelPlanState(**base)


def test_all_rain_all_outdoor_route_gets_weather_exposure_l1():
    report = hard_constraint_report(_weather_state())

    assert [item["code"] for item in report["l1"]].count("weather_exposure_conflict") == 1
    assert not report["l0"]


def test_single_rainy_day_does_not_trigger_weather_exposure():
    state = _weather_state(weather_forecast=[
        {"date": "2026-10-15", "is_bad": True},
        {"date": "2026-10-16", "is_bad": False},
    ])

    assert "weather_exposure_conflict" not in [item["code"] for item in hard_constraint_report(state)["l1"]]


def test_missing_weather_or_indoor_spot_does_not_trigger_weather_exposure():
    no_weather = _weather_state(weather_forecast=[])
    indoor = _weather_state(pois=[
        {"name": "海滩A", "indoor": False}, {"name": "海滩B", "indoor": True},
    ])

    assert "weather_exposure_conflict" not in [item["code"] for item in hard_constraint_report(no_weather)["l1"]]
    assert "weather_exposure_conflict" not in [item["code"] for item in hard_constraint_report(indoor)["l1"]]


def test_weather_exposure_l1_downgrades_to_partial_not_success():
    state = TravelPlanState(query="x", route_history=[
        snapshot(1, 90, l1=[{"code": "weather_exposure_conflict", "message": "全程雨且全室外"}]),
    ])

    chosen, status, warnings, failures = choose_snapshot(state)

    assert chosen["iteration"] == 1
    assert status == "PARTIAL_SUCCESS"
    assert "全程雨且全室外" in warnings
    assert not failures


def test_physical_time_deadlock_is_hard_reject():
    state = TravelPlanState(query="x", route_history=[
        snapshot(1, 95, l1=[{"code": "physical_time_deadlock", "message": "时间窗口不足"}]),
    ])

    chosen, status, warnings, failures = choose_snapshot(state)

    assert chosen["iteration"] == 1
    assert status == "FAILED"
    assert warnings == []
    assert failures[0]["code"] == "physical_time_deadlock"
    assert failures[0]["stage"] == "L1_INFEASIBLE"


def test_deliverable_l1_is_preferred_over_physical_deadlock():
    state = TravelPlanState(query="x", route_history=[
        snapshot(1, 95, l1=[{"code": "physical_time_deadlock", "message": "时间窗口不足"}]),
        snapshot(2, 80, l1=[{"code": "opening_time_conflict", "message": "开放时间冲突"}]),
    ])

    chosen, status, warnings, _failures = choose_snapshot(state)

    assert chosen["iteration"] == 2
    assert status == "PARTIAL_SUCCESS"
    assert "开放时间冲突" in warnings


def _physical_state() -> TravelPlanState:
    route = [{"day": 1, "spots": [
        {"name": "A", "start_time": "14:00", "end_time": "15:30"},
        {"name": "B", "start_time": "15:30", "end_time": "17:00"},
    ]}]
    return TravelPlanState(
        query="只有14:00到16:00两小时，每处至少90分钟，必须去“A”“B”，不能删减。",
        destination="X", days=1, max_per_day=3, max_review_rounds=3,
        pois=[{"name": "A"}, {"name": "B"}],
        route=route,
        route_history=[snapshot(1, 80, l1=[{"code": "physical_time_deadlock", "message": "时间窗口不足"}])],
        review_round=1,
    )


def test_route_after_review_short_circuits_physical_deadlock():
    state = _physical_state()

    assert terminal_infeasibility(state)
    assert route_after_review(state) == "finalize"


def test_route_after_review_short_circuits_candidate_pool_conflict():
    state = TravelPlanState(
        query="三亚一天，只想去室内。", destination="三亚", days=1, max_per_day=3,
        pois=[{"name": "海滩", "indoor": False}],
        route=[{"day": 1, "spots": [{"name": "海滩"}]}],
        route_history=[snapshot(1, 80, l0=[
            {"code": "candidate_pool_preference_conflict", "message": "池中无室内景点"},
        ])],
        review_round=1,
    )

    assert terminal_infeasibility(state)
    assert route_after_review(state) == "finalize"


def _same_route_snapshot(iteration: int) -> dict:
    return {
        "iteration": iteration,
        "plan": {"route": [{"day": 1, "spots": [{"name": "A"}]}], "meal_slots": []},
        "l0_violations": [{"code": "missing_must_visit", "message": "缺少点名景点"}],
        "l1_violations": [],
        "soft_score": 80,
        "reviewer_approved": False,
        "reviewer_warnings": [],
        "rework_instructions": ["补回点名景点"],
    }


def test_route_after_review_stops_when_two_snapshots_are_identical():
    state = TravelPlanState(
        query="x", destination="X", days=1, max_review_rounds=3,
        pois=[{"name": "A"}],
        route=[{"day": 1, "spots": [{"name": "A"}]}],
        route_history=[_same_route_snapshot(1), _same_route_snapshot(2)],
        review_round=2,
    )

    assert route_after_review(state) == "finalize"


def test_result_envelope_keeps_failed_plan_object_shape():
    state = TravelPlanState(
        query="x", result_status="FAILED",
        failure_reasons=[{"code": "named_poi_unavailable", "message": "未找到指定景点", "stage": "PRECHECK"}],
        final_plan={"days": [], "route_issues": []},
    )
    result = result_envelope(state)
    assert result["status"] == "FAILED"
    assert result["plan"]["days"] == []
    assert result["failure_reasons"][0]["code"] == "named_poi_unavailable"
