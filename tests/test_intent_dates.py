"""意图日期解析的确定性兜底回归。"""

from datetime import date

from app.planning.helpers import (
    extract_travel_days,
    parse_explicit_travel_dates,
    parse_relative_travel_date,
)
from app.planning.schemas import IntentExtraction, TravelPlanState


def test_month_day_without_year_uses_current_or_next_year():
    assert parse_explicit_travel_dates("杭州一日，西湖边慢慢走,11.18开始", date(2026, 11, 5)) == [
        date(2026, 11, 18)
    ]
    # 日期已过则顺延到下一年。
    assert parse_explicit_travel_dates("11.18 出发", date(2026, 11, 20)) == [
        date(2027, 11, 18)
    ]


def test_full_dates_and_ranges_are_supported():
    assert parse_explicit_travel_dates("2026年11月18日出发", date(2026, 11, 5)) == [
        date(2026, 11, 18)
    ]
    assert parse_explicit_travel_dates("11月18日到11月20日", date(2026, 11, 5)) == [
        date(2026, 11, 18), date(2026, 11, 20)
    ]


def test_duration_units_are_not_misread_as_dates():
    assert parse_explicit_travel_dates("只要 1.5小时", date(2026, 11, 5)) == []
    assert parse_explicit_travel_dates("步行 3.5公里", date(2026, 11, 5)) == []


def test_travel_days_extraction_avoids_date_suffixes():
    assert extract_travel_days("杭州一日，西湖边慢慢走") == 1
    assert extract_travel_days("三天两夜") == 3
    assert extract_travel_days("五日游") == 5
    assert extract_travel_days("两日游") == 2
    assert extract_travel_days("11月18日出发") is None
    assert extract_travel_days("第3日") is None


def test_relative_dates_are_resolved_without_llm():
    friday = date(2026, 11, 6)
    assert parse_relative_travel_date("明天中午开始", friday) == date(2026, 11, 7)
    assert parse_relative_travel_date("后天出发", friday) == date(2026, 11, 8)
    assert parse_relative_travel_date("大后天", friday) == date(2026, 11, 9)
    assert parse_relative_travel_date("三天后出发", friday) == date(2026, 11, 9)
    assert parse_relative_travel_date("周末两天", friday) == date(2026, 11, 7)
    assert parse_relative_travel_date("下周末去", friday) == date(2026, 11, 14)
    assert parse_relative_travel_date("下周六出发", friday) == date(2026, 11, 14)
    assert parse_relative_travel_date("周六出发", friday) == date(2026, 11, 7)
    # 周六当天说「周末」就是当天；周日说「周末」顺延到下一个周六。
    assert parse_relative_travel_date("周末去", date(2026, 11, 7)) == date(2026, 11, 7)
    assert parse_relative_travel_date("周末去", date(2026, 11, 8)) == date(2026, 11, 14)
    assert parse_relative_travel_date("没有日期", friday) is None


class _FakeIntentLLM:
    model_name = "fake-intent"

    def invoke(self, messages):
        return IntentExtraction(
            destination="杭州",
            travel_start_date="",
            travel_end_date="",
            travel_days=0,
        )


def test_intent_node_fills_explicit_date_and_duration(monkeypatch):
    from app.planning import nodes

    monkeypatch.setattr(nodes, "build_structured_llm", lambda *args, **kwargs: _FakeIntentLLM())
    update = nodes.make_intent_node(None)(
        TravelPlanState(query="2026-11-18开始，杭州一日，西湖边慢慢走")
    )

    assert update["travel_start_date"] == date(2026, 11, 18)
    assert update["travel_end_date"] == date(2026, 11, 18)
    assert update["days"] == 1
    assert update["missing_fields"] == []


def test_intent_node_fills_relative_date_and_duration(monkeypatch):
    from app.planning import nodes

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 6)   # 周五

    monkeypatch.setattr(nodes, "date", _FixedDate)
    monkeypatch.setattr(nodes, "build_structured_llm", lambda *args, **kwargs: _FakeIntentLLM())
    update = nodes.make_intent_node(None)(
        TravelPlanState(query="成都周末两天，想泡茶馆吃火锅,明天中午开始")
    )

    assert update["travel_start_date"] == date(2026, 11, 7)
    assert update["travel_end_date"] == date(2026, 11, 8)
    assert update["days"] == 2
    assert update["missing_fields"] == []


def test_explicit_date_overrides_model_misread(monkeypatch):
    from app.planning import nodes

    class _WrongDateLLM(_FakeIntentLLM):
        def invoke(self, messages):
            return IntentExtraction(
                destination="杭州",
                travel_start_date="2026-11-19",
                travel_end_date="2026-11-19",
                travel_days=1,
            )

    monkeypatch.setattr(nodes, "build_structured_llm", lambda *args, **kwargs: _WrongDateLLM())
    update = nodes.make_intent_node(None)(
        TravelPlanState(query="2026-11-18开始，杭州一日")
    )

    assert update["travel_start_date"] == date(2026, 11, 18)
    assert update["travel_end_date"] == date(2026, 11, 18)
