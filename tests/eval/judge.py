"""语义质量评委（LLM Judge）框架。

默认离线：``stub`` 只验证管线，``replay`` 只读缓存，``llm`` 必须显式放行。
Judge 只看盲评 payload（目的地、日期、偏好、天气、路线、候选池规模），
不接收 status / L0 / L1 / benchmark_label / mode / 模型名。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.core.llm_usage import snapshot as usage_snapshot, usage_delta
from app.planning.helpers import invoke_structured

RUBRIC_VERSION = "judge-rubric-v2"
PROMPT_VERSION = "judge-prompt-v2"
DIMENSIONS: dict[str, dict[str, Any]] = {
    "preference_fit": {"weight": 20, "label": "偏好契合"},
    "pacing": {"weight": 15, "label": "节奏与强度"},
    "geographic_coherence": {"weight": 15, "label": "地理连贯"},
    "time_realism": {"weight": 20, "label": "时间与开放现实性"},
    "completeness": {"weight": 15, "label": "信息完整与可执行"},
    "diversity_and_dining": {"weight": 15, "label": "多样性与餐饮"},
}
FORBIDDEN_PAYLOAD_KEYS = {
    "status", "l0_codes", "l1_codes", "benchmark_label", "actual_outcome",
    "mode_requested", "mode_effective", "soft_score", "reviewer_approved",
    "model_name", "trial_id",
}
CANONICAL_FLAGS = {
    "bad_weather_all_days", "pacing_too_tight", "geographic_inefficiency",
    "early_start_conflict", "preference_mismatch", "incomplete_practical_info",
    "limited_diversity", "missing_dining", "missing_transport", "invented_place",
    "unsafe_advice", "evidence_missing", "other",
}
_FLAG_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("雨", "weather", "rain"), "bad_weather_all_days"),
    (("packed", "tight", "紧凑", "过多", "gap", "数量偏多"), "pacing_too_tight"),
    (("geographic", "地理", "分散", "折返", "inefficiency"), "geographic_inefficiency"),
    (("early", "早起"), "early_start_conflict"),
    (("preference", "偏好", "不符", "mismatch"), "preference_mismatch"),
    (("diversity", "variety", "单一", "类型有限", "重复"), "limited_diversity"),
    (("dining", "meal", "餐饮", "用餐"), "missing_dining"),
    (("transport", "交通", "通勤", "logistics"), "missing_transport"),
    (("invent", "虚构", "不存在"), "invented_place"),
    (("unsafe", "危险", "安全"), "unsafe_advice"),
    (("incomplete", "信息", "practical", "实用", "details", "completeness"), "incomplete_practical_info"),
)
DEFAULT_CACHE_DIR = Path("evaluation/judge/cache")


class JudgeScores(BaseModel):
    preference_fit: int = Field(ge=0, le=5)
    pacing: int = Field(ge=0, le=5)
    geographic_coherence: int = Field(ge=0, le=5)
    time_realism: int = Field(ge=0, le=5)
    completeness: int = Field(ge=0, le=5)
    diversity_and_dining: int = Field(ge=0, le=5)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    overall_comment: str = ""


class JudgeBudgetExceeded(RuntimeError):
    pass


JUDGE_SYSTEM = """你是严格的旅行行程质量评委。只评价给出的路线，不要假设未提供的信息。
六个维度各 0-5 分：
- preference_fit：与用户偏好、习惯、必去点的契合度；
- pacing：每天节奏与强度是否合理，是否过满或过空；
- geographic_coherence：景点地理顺序是否少折返；
- time_realism：时间安排是否现实，含通勤与开放时间常识；
- completeness：路线信息（景点、时间、顺序）是否完整、可直接执行；
- diversity_and_dining：体验是否多样；餐饮仅在 scope.meals=true 时评价。
评测范围由 payload.scope 声明：
- scope.meals=false 时，不要因缺少餐饮安排扣分；
- scope.transport_legs=false 时，不要因缺少交通方式/通勤时间扣分；
- scope.live_info=false 时，不要因缺少门票、实时价格、排队信息扣分；
- 只评价已提供的路线、时间与偏好契合，不要虚构缺失信息。
每个维度必须给出 reason 和 evidence（引用路线中的 Day/景点名）。不要因为措辞好听而加分。
输出 JSON，不要输出额外文本。"""


# ─── 盲评 payload ──────────────────────────────────────────

def _normalize_spots(route: list[dict[str, Any]]) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for index, day in enumerate(route or []):
        spots = []
        for spot in day.get("spots") or []:
            if not isinstance(spot, dict):
                continue
            spots.append({
                "name": spot.get("name"),
                "period": spot.get("period"),
                "start": spot.get("start") or spot.get("start_time"),
                "end": spot.get("end") or spot.get("end_time"),
            })
        days.append({"day": int(day.get("day") or index + 1), "spots": spots})
    return days


def build_payload(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """构造盲评输入；禁止把判定码、标签、模式或模型名带进去。"""
    route = record.get("delivered_route_by_day") or record.get("route_by_day") or []
    payload = {
        "destination": case.get("destination"),
        "days": case.get("days"),
        "dates": {
            "start": case.get("travel_start_date"),
            "end": case.get("travel_end_date"),
        },
        "preferences": {
            "attraction": case.get("attraction_preference"),
            "food": case.get("food_preference"),
            "habit": case.get("habit_preference"),
            "max_walking_km": case.get("max_walking_km"),
        },
        "weather": [
            {
                "date": item.get("date"),
                "day_weather": item.get("day_weather"),
                "is_bad": bool(item.get("is_bad")),
            }
            for item in (case.get("weather_forecast") or [])
        ],
        "route": _normalize_spots(route),
        "candidate_pool_size": len(case.get("pois") or []),
        "scope": {
            "meals": bool(record.get("meal_slots")),
            "transport_legs": int(record.get("route_leg_count") or 0) > 0,
            "live_info": False,
        },
    }
    leaked = FORBIDDEN_PAYLOAD_KEYS & set(payload)
    if leaked:
        raise ValueError(f"judge payload contains forbidden keys: {sorted(leaked)}")
    return payload


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def cache_key(payload: dict[str, Any], judge_id: int, model: str | None, provider: str) -> str:
    # stub 与真实运行必须隔离；replay 读取真实运行缓存。
    provider_key = "stub" if provider == "stub" else "runtime"
    material = {
        "payload_hash": payload_hash(payload),
        "rubric_version": RUBRIC_VERSION,
        "prompt_version": PROMPT_VERSION,
        "judge_id": int(judge_id),
        "model": model or "default",
        "provider": provider_key,
    }
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


# ─── 评分计算 ──────────────────────────────────────────────

def weighted_score(scores: dict[str, int]) -> float:
    total = 0.0
    for name, meta in DIMENSIONS.items():
        total += float(scores.get(name, 0)) / 5.0 * float(meta["weight"])
    return round(total, 2)


def quadratic_weighted_kappa(a: list[int], b: list[int], minimum: int = 0, maximum: int = 5) -> float | None:
    if not a or len(a) != len(b):
        return None
    size = maximum - minimum + 1
    observed = [[0.0] * size for _ in range(size)]
    for left, right in zip(a, b):
        observed[int(left) - minimum][int(right) - minimum] += 1
    total = float(len(a))
    hist_a = [sum(row) for row in observed]
    hist_b = [sum(observed[row][col] for row in range(size)) for col in range(size)]
    expected = [[hist_a[i] * hist_b[j] / total for j in range(size)] for i in range(size)]
    numerator = 0.0
    denominator = 0.0
    for i in range(size):
        for j in range(size):
            weight = ((i - j) ** 2) / ((size - 1) ** 2)
            numerator += weight * observed[i][j]
            denominator += weight * expected[i][j]
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return round(1.0 - numerator / denominator, 4)


def agreement(judge_scores: list[dict[str, int]]) -> dict[str, Any] | None:
    if len(judge_scores) < 2:
        return None
    a, b = judge_scores[0], judge_scores[1]
    pairs = [(int(a.get(name, 0)), int(b.get(name, 0))) for name in DIMENSIONS]
    exact = sum(1 for left, right in pairs if left == right)
    within_one = sum(1 for left, right in pairs if abs(left - right) <= 1)
    diffs = [abs(left - right) for left, right in pairs]
    return {
        "dimensions": len(pairs),
        "exact": exact,
        "within_one": within_one,
        "exact_rate": round(exact / len(pairs), 4),
        "within_one_rate": round(within_one / len(pairs), 4),
        "mean_abs_diff": round(sum(diffs) / len(diffs), 3),
        "quadratic_weighted_kappa": quadratic_weighted_kappa(
            [left for left, _ in pairs], [right for _, right in pairs]
        ),
    }


# ─── providers ─────────────────────────────────────────────

def normalize_flags(
    flags: list[str] | None,
    evidence: dict[str, list[str]] | None,
    reasons: dict[str, str] | None,
) -> list[str]:
    """把模型自由文本 flags 收敛为固定集合，并用 reasons 回退证据。"""
    mapped: set[str] = set()
    for raw in flags or []:
        text = str(raw).lower()
        if "evidence_missing" in text:
            continue
        for keywords, canonical in _FLAG_KEYWORDS:
            if any(keyword.lower() in text for keyword in keywords):
                mapped.add(canonical)
                break
        else:
            mapped.add("other")
    evidence = evidence or {}
    reasons = reasons or {}
    missing = [
        name for name in DIMENSIONS
        if not evidence.get(name) and not reasons.get(name)
    ]
    if missing:
        mapped.add("evidence_missing")
    return sorted(mapped)


def _stub_scores(payload: dict[str, Any], judge_id: int) -> dict[str, Any]:
    route = payload.get("route") or []
    spots = [spot for day in route for spot in (day.get("spots") or [])]
    names = [str(spot.get("name") or "") for spot in spots]
    counts = [len(day.get("spots") or []) for day in route]
    base = 4 if spots else 1
    preference = base if len(spots) >= min(int(payload.get("days") or 1), 2) else max(1, base - 2)
    pacing = base if all(count <= 3 for count in counts) else max(1, base - 2)
    geographic = base if len(names) == len(set(names)) else max(1, base - 2)
    time_realism = base if all(spot.get("start") and spot.get("end") for spot in spots) else max(1, base - 2)
    completeness = 5 if spots else 1
    diversity = 3 if spots else 1
    if judge_id % 2 == 0:
        pacing = min(5, pacing + 1)
    scores = {
        "preference_fit": preference,
        "pacing": pacing,
        "geographic_coherence": geographic,
        "time_realism": time_realism,
        "completeness": completeness,
        "diversity_and_dining": diversity,
    }
    evidence = {name: [name for name in names[:3]] for name in DIMENSIONS}
    return {
        **scores,
        "evidence": evidence,
        "reasons": {name: f"stub judge {judge_id} 仅用于管线自测" for name in DIMENSIONS},
        "flags": ["stub_provider"],
        "overall_comment": "stub provider: never use as a quality result",
    }


def _validate_response(response: Any) -> dict[str, Any]:
    if isinstance(response, JudgeScores):
        data = response.model_dump()
    elif isinstance(response, dict):
        data = JudgeScores(**response).model_dump()
    else:
        raise ValueError(f"judge response is not a dict/schema: {type(response)!r}")
    missing_evidence = [
        name for name in DIMENSIONS
        if not data.get("evidence", {}).get(name) and not data.get("reasons", {}).get(name)
    ]
    data["flags"] = normalize_flags(data.get("flags"), data.get("evidence"), data.get("reasons"))
    if missing_evidence:
        data["flags"] = sorted(set(data["flags"]) | {"evidence_missing"})
    return data


def _call_llm(payload: dict[str, Any], model: str | None, llm: Any | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if llm is None:
        from app.llm.factory import build_structured_llm

        llm = build_structured_llm(JudgeScores, model=model, temperature=0, task_type="judge")
    before = usage_snapshot()
    result = invoke_structured(llm, [("system", JUDGE_SYSTEM), ("human", _canonical(payload))])
    usage = usage_delta(before, usage_snapshot())
    return _validate_response(result), usage


def call_judge(
    payload: dict[str, Any],
    *,
    provider: str,
    judge_id: int,
    model: str | None,
    cache_dir: Path,
    judge_fn: Callable[..., dict[str, Any]] | None = None,
    llm: Any | None = None,
    budget: "JudgeBudget" | None = None,
) -> dict[str, Any]:
    key = cache_key(payload, judge_id, model, provider)
    cache_path = cache_dir / f"{key}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_flags = normalize_flags(
                cached.get("flags"), cached.get("evidence"), cached.get("reasons")
            )
            return {
                "judge_id": judge_id,
                "scores": cached["scores"],
                "weighted_score": weighted_score(cached["scores"]),
                "evidence": cached.get("evidence", {}),
                "reasons": cached.get("reasons", {}),
                "flags": cached_flags,
                "overall_comment": cached.get("overall_comment", ""),
                "cache_hit": True,
                "usage": cached.get("usage", {}),
            }
        except (KeyError, json.JSONDecodeError, OSError):
            pass

    if provider == "replay":
        return {"judge_id": judge_id, "error": "cache_miss", "cache_hit": False}
    if budget is not None:
        budget.consume()

    if judge_fn is not None:
        try:
            data = _validate_response(judge_fn(payload, judge_id=judge_id))
        except Exception as exc:  # noqa: BLE001 - 评委输出异常不能中断整批评测
            return {"judge_id": judge_id, "error": f"invalid_response: {exc}", "cache_hit": False}
        usage: dict[str, Any] = {}
    elif provider == "stub":
        data = _validate_response(_stub_scores(payload, judge_id))
        usage = {}
    elif provider == "llm":
        try:
            data, usage = _call_llm(payload, model, llm)
        except Exception as exc:  # noqa: BLE001 - 供应商/解析错误转为 judge_error
            return {"judge_id": judge_id, "error": f"invalid_response: {exc}", "cache_hit": False}
    else:
        raise ValueError(f"unknown judge provider: {provider}")

    record = {
        "scores": {name: int(data[name]) for name in DIMENSIONS},
        "evidence": data.get("evidence", {}),
        "reasons": data.get("reasons", {}),
        "flags": data.get("flags", []),
        "overall_comment": data.get("overall_comment", ""),
        "usage": usage,
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({
            "key": key,
            "rubric_version": RUBRIC_VERSION,
            "prompt_version": PROMPT_VERSION,
            "judge_id": judge_id,
            "model": model,
            "payload_hash": payload_hash(payload),
            **record,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "judge_id": judge_id,
        **record,
        "weighted_score": weighted_score(record["scores"]),
        "cache_hit": False,
    }


class JudgeBudget:
    def __init__(self, limit: int = 0):
        self.limit = max(0, int(limit))
        self.used = 0

    def consume(self) -> None:
        if self.limit and self.used >= self.limit:
            raise JudgeBudgetExceeded(f"judge call budget exceeded: {self.limit}")
        self.used += 1


# ─── 单记录评分 ────────────────────────────────────────────

def score_record(
    case: dict[str, Any],
    record: dict[str, Any],
    *,
    provider: str = "stub",
    k: int = 2,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    model: str | None = None,
    judge_fn: Callable[..., dict[str, Any]] | None = None,
    llm: Any | None = None,
    budget: JudgeBudget | None = None,
) -> dict[str, Any]:
    if not record.get("plan_generated"):
        return {"skipped": True, "reason": "not_delivered"}
    payload = build_payload(case, record)
    if not payload.get("route"):
        return {"skipped": True, "reason": "empty_route"}

    judges: list[dict[str, Any]] = []
    errors: list[str] = []
    for judge_id in range(1, max(1, int(k)) + 1):
        result = call_judge(
            payload, provider=provider, judge_id=judge_id, model=model,
            cache_dir=cache_dir, judge_fn=judge_fn, llm=llm, budget=budget,
        )
        if result.get("error"):
            errors.append(f"judge{judge_id}: {result['error']}")
        else:
            judges.append(result)

    if not judges:
        return {
            "rubric_version": RUBRIC_VERSION,
            "prompt_version": PROMPT_VERSION,
            "provider": provider,
            "model": model,
            "error": "; ".join(errors) or "no_judge_result",
            "judge_calls": 0,
            "judge_tokens_est": 0,
            "judges": [],
        }

    dimension_mean = {
        name: round(sum(item["scores"][name] for item in judges) / len(judges), 3)
        for name in DIMENSIONS
    }
    overall_mean = round(sum(item["weighted_score"] for item in judges) / len(judges), 2)
    low = [name for name, value in dimension_mean.items() if value <= 2.0]
    usage_totals = [
        int((item.get("usage") or {}).get("total_tokens") or 0) for item in judges
    ]
    flags = sorted({flag for item in judges for flag in (item.get("flags") or [])})
    return {
        "rubric_version": RUBRIC_VERSION,
        "prompt_version": PROMPT_VERSION,
        "provider": provider,
        "model": model,
        "judges": judges,
        "overall_mean": overall_mean,
        "dimension_mean": dimension_mean,
        "agreement": agreement([item["scores"] for item in judges]),
        "low_score_dimensions": low,
        "flags": flags,
        "judge_calls": sum(0 if item.get("cache_hit") else 1 for item in judges),
        "replayed_calls": sum(
            1 for item in judges
            if item.get("cache_hit") and int((item.get("usage") or {}).get("total_tokens") or 0) > 0
        ),
        "judge_tokens_est": sum(usage_totals),
        "cache_hits": sum(1 for item in judges if item.get("cache_hit")),
        "errors": errors,
    }


# ─── 汇总与报告 ────────────────────────────────────────────

def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [item for item in results if item.get("judge") and not item["judge"].get("skipped")]
    valid = [item for item in scored if item["judge"].get("overall_mean") is not None]
    dims = {
        name: round(
            sum(float(item["judge"]["dimension_mean"][name]) for item in valid) / len(valid), 3
        ) if valid else None
        for name in DIMENSIONS
    }
    kappas = [
        item["judge"]["agreement"]["quadratic_weighted_kappa"]
        for item in valid
        if item["judge"].get("agreement")
        and item["judge"]["agreement"].get("quadratic_weighted_kappa") is not None
    ]
    pooled_left: list[int] = []
    pooled_right: list[int] = []
    for item in valid:
        judges = item["judge"].get("judges") or []
        if len(judges) < 2:
            continue
        for name in DIMENSIONS:
            pooled_left.append(int(judges[0]["scores"][name]))
            pooled_right.append(int(judges[1]["scores"][name]))
    kappa_pooled = quadratic_weighted_kappa(pooled_left, pooled_right) if pooled_left else None
    low = [
        {"target_id": item.get("target_id"), "overall": item["judge"].get("overall_mean")}
        for item in valid
        if float(item["judge"].get("overall_mean") or 0) < 60.0
    ]
    flag_counts: dict[str, int] = {}
    for item in valid:
        for judge_block in item["judge"].get("judges") or []:
            for flag in judge_block.get("flags") or []:
                flag_counts[str(flag)] = flag_counts.get(str(flag), 0) + 1
    by_case: dict[str, list[float]] = {}
    for item in valid:
        by_case.setdefault(str(item.get("case_id")), []).append(float(item["judge"]["overall_mean"]))
    scored_rows = [item["judge"] for item in results if not item["judge"].get("skipped")]
    return {
        "provider": next((row.get("provider") for row in scored_rows if row.get("provider")), None),
        "model": next((row.get("model") for row in scored_rows if row.get("model")), None),
        "targets": len(results),
        "scored": len(valid),
        "skipped": len(results) - len(scored),
        "coverage": round(len(valid) / len(results), 4) if results else None,
        "overall_mean": round(sum(float(item["judge"]["overall_mean"]) for item in valid) / len(valid), 2) if valid else None,
        "dimension_mean": dims,
        "kappa_mean": round(sum(kappas) / len(kappas), 4) if kappas else None,
        "kappa_pooled": kappa_pooled,
        "judge_calls": sum(int(item["judge"].get("judge_calls") or 0) for item in valid),
        "replayed_calls": sum(int(item["judge"].get("replayed_calls") or 0) for item in valid),
        "judge_tokens_est": sum(int(item["judge"].get("judge_tokens_est") or 0) for item in valid),
        "cache_hits": sum(int(item["judge"].get("cache_hits") or 0) for item in valid),
        "errors": [
            {"target_id": item.get("target_id"), "error": item["judge"].get("error")}
            for item in results
            if item["judge"].get("error")
        ],
        "low_score": low,
        "low_score_threshold": 60.0,
        "flag_counts": dict(sorted(flag_counts.items())),
        "by_case": {
            case: round(sum(values) / len(values), 2) for case, values in sorted(by_case.items())
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    dims = summary.get("dimension_mean") or {}
    return "\n".join([
        "# 语义质量 Judge",
        "",
        f"- provider：{summary.get('provider')}；model：{summary.get('model') or 'default'}",
        f"- targets：{summary.get('targets')}；有效评分：{summary.get('scored')}；"
        f"覆盖率：{summary.get('coverage')}",
        f"- 总分均值：{summary.get('overall_mean')}（0-100，仅对已交付路线）",
        f"- 双评 kappa 均值：{summary.get('kappa_mean')}；合并 kappa：{summary.get('kappa_pooled')}",
        f"- Judge 调用：{summary.get('judge_calls')}；缓存重放：{summary.get('replayed_calls')}；"
        f"估算 Token：{summary.get('judge_tokens_est')}；缓存命中：{summary.get('cache_hits')}",
        "",
        "| 维度 | 均值（0-5） |",
        "|---|---|",
        *[f"| {meta['label']} `{name}` | {dims.get(name)} |" for name, meta in DIMENSIONS.items()],
        "",
        f"- 低分 target（<60）：{summary.get('low_score')}",
        f"- Judge flags：{summary.get('flag_counts')}",
        f"- 按 case：{summary.get('by_case')}",
        f"- 校准：{summary.get('calibration')}",
        f"- 错误：{summary.get('errors')}",
        "",
        "> stub provider 仅用于管线自测，不得当作质量结果。",
    ])


def calibration_report(results: list[dict[str, Any]], labels: dict[str, float]) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for item in results:
        target = str(item.get("target_id") or "")
        judge = item.get("judge") or {}
        if target in labels and judge.get("overall_mean") is not None:
            pairs.append((float(labels[target]), float(judge["overall_mean"])))
    if len(pairs) < 2:
        return {"n": len(pairs), "mae": None, "spearman": None, "band_agreement": None}

    def _band(value: float) -> int:
        if value < 40:
            return 0
        if value < 60:
            return 1
        if value < 80:
            return 2
        return 3

    def _ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda index: values[index])
        ranks = [0.0] * len(values)
        index = 0
        while index < len(order):
            end = index
            while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
                end += 1
            average = (index + end) / 2.0 + 1
            for position in range(index, end + 1):
                ranks[order[position]] = average
            index = end + 1
        return ranks

    human = [pair[0] for pair in pairs]
    judged = [pair[1] for pair in pairs]
    mae = sum(abs(left - right) for left, right in pairs) / len(pairs)
    rank_h, rank_j = _ranks(human), _ranks(judged)
    n = len(pairs)
    d2 = sum((left - right) ** 2 for left, right in zip(rank_h, rank_j))
    spearman = 1 - (6 * d2) / (n * (n * n - 1)) if n > 1 else None
    bands = sum(1 for left, right in pairs if _band(left) == _band(right))
    return {
        "n": n,
        "mae": round(mae, 3),
        "spearman": round(spearman, 4) if spearman is not None else None,
        "band_agreement": round(bands / n, 4),
    }


# ─── 目标加载与 CLI ────────────────────────────────────────

def load_trial_targets(dirs: list[Path], cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for directory in dirs:
        for path in sorted(directory.glob("trial_*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            case = cases.get(str(record.get("case_id")))
            if case is None:
                continue
            targets.append({
                "target_id": str(record.get("trial_id")),
                "case_id": record.get("case_id"),
                "case": case,
                "record": record,
            })
    return targets


def load_checkpoint_targets(directory: Path, cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    raw = directory / "raw" if (directory / "raw").exists() else directory
    targets: list[dict[str, Any]] = []
    for path in sorted(raw.glob("pair_*.json")):
        pair = json.loads(path.read_text(encoding="utf-8"))
        case = cases.get(str(pair.get("case_id")))
        if case is None:
            continue
        for arm in ("A", "B"):
            data = pair.get(arm) or {}
            route = data.get("route") or []
            record = {
                "trial_id": f"{path.stem}_{arm}",
                "case_id": pair.get("case_id"),
                "plan_generated": bool(data.get("plan_generated", bool(route))),
                "status": data.get("status"),
                "route_by_day": route,
            }
            targets.append({
                "target_id": record["trial_id"],
                "case_id": record["case_id"],
                "case": case,
                "record": record,
            })
    return targets


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Travelmind semantic judge")
    parser.add_argument("--trials", action="append", type=Path, default=None)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--version", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--provider", default="stub", choices=["stub", "replay", "llm"])
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--calibration-labels", type=Path, default=None)
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--allow-external-calls", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from app.core.env import load_local_env

    load_local_env()
    if args.provider == "llm" and not args.allow_external_calls:
        print("llm provider 会产生真实调用；确认后追加 --allow-external-calls。", file=sys.stderr)
        return 2
    if args.provider == "llm" and args.max_calls <= 0:
        print("llm provider 必须显式设置 --max-calls 硬预算。", file=sys.stderr)
        return 2

    from tests.eval import harness

    cases = {case["id"]: case for case in harness.load_cases(version=args.version)}
    targets: list[dict[str, Any]] = []
    if args.trials:
        targets.extend(load_trial_targets(args.trials, cases))
    if args.checkpoint_dir:
        targets.extend(load_checkpoint_targets(args.checkpoint_dir, cases))
    if not targets:
        print("没有可评分的 target（需要 route_by_day 或 checkpoint route）。", file=sys.stderr)
        return 1

    model = args.model or os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL")
    budget = JudgeBudget(args.max_calls)
    results: list[dict[str, Any]] = []
    args.out.mkdir(parents=True, exist_ok=True)
    for index, target in enumerate(targets, 1):
        judge = score_record(
            target["case"], target["record"],
            provider=args.provider, k=args.k, cache_dir=args.cache_dir,
            model=model, budget=budget,
        )
        results.append({**target, "judge": judge})
        if not judge.get("skipped"):
            path = args.out / f"judge_{target['target_id']}.json"
            path.write_text(json.dumps({
                "trial_id": target["record"].get("trial_id"),
                "case_id": target["case_id"],
                "judge": judge,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        status = "skip" if judge.get("skipped") else judge.get("overall_mean")
        print(f"[{index}/{len(targets)}] {target['target_id']} -> {status}")

    summary = summarize(results)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["k"] = max(1, args.k)
    if args.calibration_labels and args.calibration_labels.exists():
        raw = json.loads(args.calibration_labels.read_text(encoding="utf-8"))
        labels = raw.get("labels", raw) if isinstance(raw, dict) else {}
        labels = {
            str(key): float(value)
            for key, value in labels.items()
            if isinstance(value, (int, float))
        }
        summary["calibration"] = calibration_report(results, labels)
    else:
        summary["calibration"] = {
            "n": 0, "mae": None, "spearman": None, "band_agreement": None,
            "note": "没有人工校准标签；N/A",
        }
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"Judge 产物：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())