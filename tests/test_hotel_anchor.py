"""住宿锚点（每天行程起点）的排时与提示回归。"""

from __future__ import annotations

from app.planning import nodes
from app.planning.nodes import (
    align_day_starts_to_anchor,
    anchor_prompt_block,
    estimate_anchor_commute_minutes,
    resolve_hotel_summary,
)
from app.planning.schemas import TravelPlanState

HOTEL = {"lat": 30.65, "lng": 104.08}


def _pois(*pairs):
    return [{"name": name, "location": {"lat": lat, "lng": lng}} for name, lat, lng in pairs]


def test_commute_estimate_buckets_by_distance():
    near = estimate_anchor_commute_minutes(HOTEL, {"lat": 30.655, "lng": 104.085})
    mid = estimate_anchor_commute_minutes(HOTEL, {"lat": 30.70, "lng": 104.15})
    far = estimate_anchor_commute_minutes(HOTEL, {"lat": 31.00, "lng": 104.60})
    assert near is not None and near < mid < far
    assert estimate_anchor_commute_minutes(None, {"lat": 1, "lng": 1}) is None


def test_first_stop_is_shifted_to_allow_commute():
    route = [{
        "day": 1,
        "spots": [
            {"name": "A", "start_time": "09:00", "end_time": "11:00"},
            {"name": "B", "start_time": "13:00", "end_time": "15:00"},
        ],
    }]
    pois = _pois(("A", 30.75, 104.20), ("B", 30.76, 104.21))
    shifted = align_day_starts_to_anchor(route, pois, HOTEL)
    assert shifted == 1
    # 首站被推后，且同日其它景点同步平移，保持相对间隔
    assert route[0]["spots"][0]["start_time"] > "09:00"
    assert route[0]["spots"][1]["start_time"] > "13:00"
    assert route[0]["spots"][1]["start_time"] > route[0]["spots"][0]["start_time"]


def test_no_shift_when_schedule_already_leaves_room():
    route = [{"day": 1, "spots": [{"name": "A", "start_time": "12:00", "end_time": "14:00"}]}]
    pois = _pois(("A", 30.655, 104.085))
    assert align_day_starts_to_anchor(route, pois, HOTEL) == 0
    assert route[0]["spots"][0]["start_time"] == "12:00"


def test_huge_deficit_is_left_to_reviewer():
    route = [{"day": 1, "spots": [{"name": "A", "start_time": "08:30", "end_time": "10:00"}]}]
    pois = _pois(("A", 40.0, 116.4))  # 成都 → 北京，远超可平移范围
    assert align_day_starts_to_anchor(route, pois, HOTEL) == 0
    assert route[0]["spots"][0]["start_time"] == "08:30"


def test_anchor_prompt_mentions_departure_and_hotel():
    block = anchor_prompt_block({"name": "全季酒店", "address": "某路 1 号", "location": HOTEL})
    assert "全季酒店" in block
    assert nodes.ANCHOR_DEPARTURE_TIME in block
    assert anchor_prompt_block(None) == ""


def test_resolve_hotel_summary_prefers_cached_state(monkeypatch):
    cached = {"name": "已选酒店", "location": HOTEL}

    def _boom(*args, **kwargs):  # 不应再请求高德
        raise AssertionError("cached hotel must not trigger a new lookup")

    monkeypatch.setattr(nodes, "recommend_chain_hotel", _boom)
    state = TravelPlanState(query="x", destination="成都", days=2, hotel_summary=cached)
    # pydantic 会复制字典，比较值即可；关键是不能再触发一次高德查询
    assert resolve_hotel_summary(state) == cached
