"""不可行性下界证明（零成本，不调用外部服务）。

只做保守判定：
- 最短游览时间 + 直线距离下界 > 时间窗 → ``INFEASIBLE``；
- 用户只要求室内但候选池没有明确室内景点 → ``INFEASIBLE``；
- 其余一律 ``UNKNOWN``，不把“下界没超窗”当成可行证明。
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

from app.planning.helpers import extract_explicit_place_requests

_WINDOW_RE = re.compile(
    r"(?:只有|仅有)\s*(\d{1,2}):(\d{2})\s*(?:到|至|-)\s*(\d{1,2}):(\d{2})\s*(?:两小时|时间窗口|窗口)?"
)
_MIN_VISIT_RE = re.compile(r"至少\s*(?:游玩|参观|停留|安排)?\s*(\d+)\s*分钟")
_INDOOR_ONLY_RE = re.compile(
    r"(?:只|仅)(?:想|要)?(?:参观|安排|去|玩)?[^，。；\n]{0,12}室内"
)
DEFAULT_SPEED_KMH = 60.0


def _clock_minutes(hour: str, minute: str) -> int:
    return int(hour) * 60 + int(minute)


def parse_window_minutes(query: str) -> int | None:
    match = _WINDOW_RE.search(query or "")
    if not match:
        return None
    start = _clock_minutes(match.group(1), match.group(2))
    end = _clock_minutes(match.group(3), match.group(4))
    return max(0, end - start)


def parse_window_range(query: str) -> tuple[int, int] | None:
    """返回 (开始分钟, 结束分钟)，供营业时间冲突判定使用。"""
    match = _WINDOW_RE.search(query or "")
    if not match:
        return None
    start = _clock_minutes(match.group(1), match.group(2))
    end = _clock_minutes(match.group(3), match.group(4))
    if end <= start:
        return None
    return start, end


_OPEN_HOURS_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(?:-|–|—|~|至)\s*(\d{1,2}):(\d{2})"
)


def parse_open_window(open_time: Any) -> tuple[int, int] | None:
    """从高德风格的 open_time 文本里取 (开门, 关门) 分钟；解析不了返回 None。"""
    match = _OPEN_HOURS_RE.search(str(open_time or ""))
    if not match:
        return None
    open_at = _clock_minutes(match.group(1), match.group(2))
    close_at = _clock_minutes(match.group(3), match.group(4))
    return (open_at, close_at) if close_at > open_at else None


def _name_in_pool(name: str, poi_map: dict[str, dict[str, Any]]) -> bool:
    if name in poi_map:
        return True
    # 高德名带地址后缀（"玄武湖景区 南京市玄武区…"），做一次前缀兼容。
    return any(key.split(" ", 1)[0] == name for key in poi_map)


def parse_min_visit_minutes(query: str) -> int | None:
    match = _MIN_VISIT_RE.search(query or "")
    return int(match.group(1)) if match else None


def haversine_km(a: dict[str, float], b: dict[str, float]) -> float:
    lat1, lng1 = math.radians(a["lat"]), math.radians(a["lng"])
    lat2, lng2 = math.radians(b["lat"]), math.radians(b["lng"])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _coords(poi: dict[str, Any]) -> dict[str, float] | None:
    location = poi.get("location") or {}
    try:
        return {"lat": float(location["lat"]), "lng": float(location["lng"])}
    except (KeyError, TypeError, ValueError):
        return None


def _min_travel_minutes(
    names: list[str],
    poi_map: dict[str, dict[str, Any]],
    speed_kmh: float = DEFAULT_SPEED_KMH,
) -> tuple[float | None, list[str]]:
    """对必去点做全排列，返回直线距离通勤下界（分钟）。"""
    points: list[dict[str, float]] = []
    missing: list[str] = []
    for name in names:
        coord = _coords(poi_map.get(name) or {})
        if coord is None:
            missing.append(name)
        else:
            points.append(coord)
    if missing:
        return None, missing
    if len(points) < 2:
        return 0.0, []
    best = math.inf
    for order in itertools.permutations(points):
        km = sum(haversine_km(a, b) for a, b in zip(order, order[1:]))
        best = min(best, km)
    return round(best / max(speed_kmh, 1.0) * 60.0, 3), []


def assess_fixture(
    fixture: dict[str, Any],
    benchmark_case: dict[str, Any] | None = None,
    *,
    speed_kmh: float = DEFAULT_SPEED_KMH,
) -> dict[str, Any]:
    """返回 ``INFEASIBLE`` / ``UNKNOWN`` 及可复核证据。"""
    benchmark_case = benchmark_case or {}
    query = str(fixture.get("query") or "")
    pois = [item for item in (fixture.get("pois") or []) if isinstance(item, dict)]
    poi_map = {str(item.get("name") or ""): item for item in pois}
    required = list(benchmark_case.get("must_visit") or []) or extract_explicit_place_requests(query)
    required = [name for name in required if name]
    window_minutes = parse_window_minutes(query)
    min_visit = parse_min_visit_minutes(query)
    evidence: dict[str, Any] = {
        "query": query,
        "required": required,
        "window_minutes": window_minutes,
        "min_visit_minutes": min_visit,
        "speed_kmh": speed_kmh,
        "indoor_true": sum(1 for item in pois if item.get("indoor") is True),
        "indoor_false": sum(1 for item in pois if item.get("indoor") is False),
        "indoor_unknown": sum(1 for item in pois if item.get("indoor") not in (True, False)),
    }

    if _INDOOR_ONLY_RE.search(query) and pois and evidence["indoor_true"] == 0:
        return {
            "verdict": "INFEASIBLE",
            "reason_code": "candidate_pool_preference_conflict",
            "message": "用户要求只去室内，但候选池没有明确室内景点",
            "evidence": evidence,
        }

    missing_required = [name for name in required if not _name_in_pool(name, poi_map)]
    if required and missing_required:
        evidence["missing_required"] = missing_required
        return {
            "verdict": "INFEASIBLE",
            "reason_code": "required_poi_unavailable",
            "message": f"用户点名景点不在可用候选池内：{'、'.join(missing_required)}",
            "evidence": evidence,
        }

    window = parse_window_range(query)
    if window is not None:
        win_start, win_end = window
        parsed = [parse_open_window(item.get("open_time")) for item in pois]
        known = [item for item in parsed if item is not None]
        evidence.update({
            "window_start_min": win_start,
            "window_end_min": win_end,
            "pois_with_open_hours": len(known),
        })
        if len(known) >= 3:
            closed_now = [
                item for item in known
                if item[1] <= win_start or item[0] >= win_end
            ]
            if len(closed_now) == len(known):
                return {
                    "verdict": "INFEASIBLE",
                    "reason_code": "opening_hours_deadlock",
                    "message": (
                        f"候选池内 {len(known)} 个景点在该时段"
                        f"（{win_start // 60:02d}:{win_start % 60:02d}-"
                        f"{win_end // 60:02d}:{win_end % 60:02d}）全部闭馆"
                    ),
                    "evidence": evidence,
                }

    if window_minutes is not None and min_visit is not None and len(required) >= 2:
        visit_minutes = len(required) * min_visit
        travel_minutes, missing = _min_travel_minutes(required, poi_map, speed_kmh)
        evidence.update({
            "visit_minutes": visit_minutes,
            "travel_minutes_lower_bound": travel_minutes,
            "missing_coordinates": missing,
        })
        if travel_minutes is None:
            return {
                "verdict": "UNKNOWN",
                "reason_code": "missing_coordinates",
                "message": "必去点缺少坐标，无法计算通勤下界",
                "evidence": evidence,
            }
        total = visit_minutes + travel_minutes
        evidence["required_minutes_lower_bound"] = round(total, 3)
        if total > window_minutes:
            return {
                "verdict": "INFEASIBLE",
                "reason_code": "physical_time_deadlock",
                "message": (
                    f"最短游览 {visit_minutes} 分钟 + 通勤下界 {travel_minutes} 分钟 "
                    f"= {round(total, 1)} 分钟，超过 {window_minutes} 分钟窗口"
                ),
                "evidence": evidence,
            }

    return {
        "verdict": "UNKNOWN",
        "reason_code": "no_provable_violation",
        "message": "没有可证明不可行的下界条件；不代表一定可行",
        "evidence": evidence,
    }


def assess_version(version: str) -> dict[str, dict[str, Any]]:
    """对某个版本的全部 case 做离线可行性判定。"""
    from tests.eval import harness

    benchmark = harness.load_benchmark(version)
    result: dict[str, dict[str, Any]] = {}
    for case in harness.load_cases(version=version):
        result[case["id"]] = assess_fixture(case, benchmark.get(case["id"], {}))
    return result