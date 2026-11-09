"""把 fixture.expectations 接入 trial 记录（零成本）。

v1 的 ``outdoor_on_bad_day_max`` 一直写在 fixture 里但从未被读取；
这里只对已交付路线做确定性校验，避免把草稿或拒绝结果算成违规。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def evaluate_expectations(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    expectations = case.get("expectations") or {}
    max_outdoor = expectations.get("outdoor_on_bad_day_max")
    if max_outdoor is None:
        return {"evaluated": False, "rule": None, "violations": []}
    if not record.get("plan_generated"):
        # 未交付就没有可评价的路线；不算通过也不算违规。
        return {"evaluated": False, "rule": "outdoor_on_bad_day_max", "violations": []}

    route = record.get("route_by_day") or []
    start_raw = case.get("travel_start_date")
    if not route or not start_raw:
        return {"evaluated": False, "rule": "outdoor_on_bad_day_max", "violations": []}

    bad_dates = {
        str(item.get("date"))
        for item in (case.get("weather_forecast") or [])
        if item.get("is_bad")
    }
    if not bad_dates:
        return {"evaluated": True, "rule": "outdoor_on_bad_day_max", "violations": []}

    indoor = {
        str(poi.get("name")): poi.get("indoor")
        for poi in (case.get("pois") or [])
        if isinstance(poi, dict)
    }
    try:
        start = date.fromisoformat(str(start_raw))
    except ValueError:
        return {"evaluated": False, "rule": "outdoor_on_bad_day_max", "violations": []}

    violations: list[dict[str, Any]] = []
    for index, day in enumerate(route):
        try:
            day_number = int(day.get("day") or index + 1)
            visit_date = (start + timedelta(days=day_number - 1)).isoformat()
        except (TypeError, ValueError):
            continue
        if visit_date not in bad_dates:
            continue
        outdoor = [
            str(spot.get("name"))
            for spot in (day.get("spots") or [])
            if indoor.get(str(spot.get("name"))) is False
        ]
        if len(outdoor) > int(max_outdoor):
            violations.append({
                "rule": "outdoor_on_bad_day_max",
                "day": day_number,
                "date": visit_date,
                "limit": int(max_outdoor),
                "outdoor_count": len(outdoor),
                "outdoor_spots": outdoor,
            })
    return {"evaluated": True, "rule": "outdoor_on_bad_day_max", "violations": violations}