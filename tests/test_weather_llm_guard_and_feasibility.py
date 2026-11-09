"""雨天室外 L1、LLM 调用墙钟上限、以及新增两类不可行机理的离线守护。"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.planning import helpers, quality
from tests.eval import feasibility


# ---------- 雨天室外 L1 ----------

def _state(*, bad_days: list[str], route: list[dict], pois: list[dict], **extra):
    forecast = [
        {"date": day, "is_bad": day in bad_days, "day_weather": "中雨" if day in bad_days else "晴"}
        for day in ("2026-08-01", "2026-08-02")
    ]
    return SimpleNamespace(
        weather_forecast=forecast,
        route=route,
        pois=pois,
        rain_indoor_priority=extra.get("rain_indoor_priority", False),
        relaxed_constraints=extra.get("relaxed_constraints", {}),
    )


def test_rain_day_with_two_outdoor_spots_reports_l1():
    state = _state(
        bad_days=["2026-08-02"],
        route=[
            {"day": 1, "spots": [{"name": "玄武湖景区"}]},
            {"day": 2, "spots": [{"name": "玄武湖景区"}, {"name": "不老村"}]},
        ],
        pois=[
            {"name": "玄武湖景区", "indoor": False},
            {"name": "不老村", "indoor": False},
        ],
    )

    violations = quality.weather_outdoor_mismatch(state)

    assert [item["code"] for item in violations] == ["weather_outdoor_mismatch"]
    assert "Day2" in violations[0]["message"]


def test_sunny_day_outdoor_spots_are_not_flagged():
    state = _state(
        bad_days=[],
        route=[{"day": 1, "spots": [{"name": "玄武湖景区"}, {"name": "不老村"}]}],
        pois=[{"name": "玄武湖景区", "indoor": False}, {"name": "不老村", "indoor": False}],
    )

    assert quality.weather_outdoor_mismatch(state) == []


def test_unknown_indoor_labels_are_not_punished():
    state = _state(
        bad_days=["2026-08-01"],
        route=[{"day": 1, "spots": [{"name": "玄武湖景区"}, {"name": "不老村"}]}],
        pois=[{"name": "玄武湖景区", "indoor": None}, {"name": "不老村", "indoor": None}],
    )

    assert quality.weather_outdoor_mismatch(state) == []


def test_indoor_priority_l0_suppresses_l1_duplicate():
    state = _state(
        bad_days=["2026-08-01"],
        route=[{"day": 1, "spots": [{"name": "玄武湖景区"}, {"name": "不老村"}]}],
        pois=[{"name": "玄武湖景区", "indoor": False}, {"name": "不老村", "indoor": False}],
        rain_indoor_priority=True,
    )

    assert quality.weather_outdoor_mismatch(state) == []


# ---------- LLM 调用墙钟上限 ----------

class _SlowLLM:
    def __init__(self, delay: float):
        self.delay = delay
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        time.sleep(self.delay)
        return None


def test_deadline_raises_timeout(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "0.2")
    slow = _SlowLLM(3.0)

    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        helpers._invoke_with_deadline(slow, [("human", "hi")])
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert helpers._llm_call_timeout_seconds() == pytest.approx(0.2)


def test_deadline_defaults_to_240_when_env_invalid(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "abc")

    assert helpers._llm_call_timeout_seconds() == pytest.approx(240.0)


def test_timeout_is_retried_by_invoke_structured(monkeypatch):
    monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "0.1")
    slow = _SlowLLM(3.0)

    with pytest.raises(TimeoutError):
        helpers.invoke_structured(slow, [("human", "hi")], retries=2)

    assert slow.calls == 2


# ---------- 新增的两类不可行机理 ----------

def _fixture(query: str, pois: list[dict]) -> dict:
    return {"query": query, "pois": pois, "id": "inline"}


def test_opening_hours_deadlock_when_pool_closed_in_window():
    pois = [
        {"name": "中山陵景区", "open_time": "08:30-17:00", "indoor": False},
        {"name": "南京牛首山文化旅游区", "open_time": "8:30-17:30", "indoor": False},
        {"name": "不老村", "open_time": "周一至周日 09:00-17:00", "indoor": False},
    ]

    verdict = feasibility.assess_fixture(
        _fixture("南京1天游，只有20:00到22:00两小时，想逛博物馆。", pois)
    )

    assert verdict["verdict"] == "INFEASIBLE"
    assert verdict["reason_code"] == "opening_hours_deadlock"


def test_daytime_window_is_not_flagged_as_closed():
    pois = [
        {"name": "中山陵景区", "open_time": "08:30-17:00", "indoor": False},
        {"name": "南京牛首山文化旅游区", "open_time": "8:30-17:30", "indoor": False},
        {"name": "不老村", "open_time": "周一至周日 09:00-17:00", "indoor": False},
    ]

    verdict = feasibility.assess_fixture(
        _fixture("南京1天游，只有10:00到16:00六小时，想逛博物馆。", pois)
    )

    assert verdict["verdict"] != "INFEASIBLE" or verdict["reason_code"] != "opening_hours_deadlock"


def test_required_poi_missing_from_pool_is_infeasible():
    pois = [{"name": "外滩", "open_time": "00:00-24:00", "indoor": False}]

    verdict = feasibility.assess_fixture(
        _fixture("上海1天游，一定要去“上海天文馆”，必须安排。", pois)
    )

    assert verdict["verdict"] == "INFEASIBLE"
    assert verdict["reason_code"] == "required_poi_unavailable"
    assert verdict["evidence"]["missing_required"] == ["上海天文馆"]
