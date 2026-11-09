"""checkpoint 恢复与局部修改候选刷新的回归测试。"""

import copy
from unittest.mock import Mock

import pytest

from app.planning.graph import restore_modification_state
from app.planning.modification import refresh_explicit_modification_candidates


def test_restore_reuses_checkpoint_and_resets_run_scoped_fields():
    checkpoint = {
        "query": "南京两日游",
        "route": [{"day": 1, "spots": [{"name": "南京博物院"}]}],
        "pois": [{"name": "南京博物院", "location": {"lat": 32, "lng": 118}}],
        "destination": "南京",
        "travel_start_date": "2026-11-06",
        "travel_end_date": "2026-11-07",
        "days": 2,
        "weather_forecast": [{"date": "2026-11-06", "text": "晴"}],
        "route_history": [{"iteration": 1, "soft_score": 90}],
        "warnings": ["旧提醒"],
        "failure_reasons": [{"code": "old"}],
        "score_info": {"current_score": 90},
        "planner_reviewer_dialogue": ["[第1轮] Reviewer 通过"],
        "review_round": 2,
        "time_check_round": 3,
    }
    before = copy.deepcopy(checkpoint)

    state = restore_modification_state(checkpoint, "第二天下午换成室内景点")

    assert checkpoint == before
    assert state.route == before["route"]
    assert state.pois == before["pois"]
    assert state.weather_forecast == before["weather_forecast"]
    assert state.planner_reviewer_dialogue == before["planner_reviewer_dialogue"]
    assert state.route_history == []
    assert state.warnings == []
    assert state.failure_reasons == []
    assert state.score_info == {}
    assert "第二天下午换成室内景点" in state.route_modify_opinion
    assert state.max_review_rounds == 2


@pytest.mark.parametrize("outcome,expected", [
    ([], "not_verified"),
    ([{"name": "同名分馆", "location": "118,32"}], "not_verified"),
    ([{"name": "新增馆", "location": ""}], "not_verified"),
    (RuntimeError("offline simulated timeout"), "provider_failed"),
    ([{"name": "新增馆", "location": "118,32"}], "added"),
])
def test_refresh_requires_matching_name_and_valid_coordinates(outcome, expected):
    checkpoint = {
        "destination": "南京",
        "pois": [{"name": "原景点", "location": {"lat": 32, "lng": 118}}],
    }
    before = copy.deepcopy(checkpoint)
    lookup = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)

    result, notes, trace = refresh_explicit_modification_candidates(
        checkpoint, "加入“新增馆”", lookup=lookup, key_provider=lambda: "offline",
    )

    assert lookup.call_count == 1
    assert trace == [{"name": "新增馆", "status": expected}]
    assert checkpoint == before
    assert len(result["pois"]) == (2 if expected == "added" else 1)
    assert ("系统已核验新增景点" in notes) == (expected == "added")


def test_refresh_does_not_search_without_destination():
    lookup = Mock(return_value=[])
    before = {"pois": []}

    result, notes, trace = refresh_explicit_modification_candidates(
        before, "加入“新馆”", lookup=lookup, key_provider=lambda: "offline",
    )

    lookup.assert_not_called()
    assert result == before
    assert notes == "加入“新馆”"
    assert trace == [{"name": "新馆", "status": "missing_destination"}]
