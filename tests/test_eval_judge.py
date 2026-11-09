"""语义质量 Judge：盲评、缓存、双评一致性、预算与校准。"""

from __future__ import annotations

import pytest

from tests.eval import judge

CASE = {
    "id": "judge-case",
    "destination": "南京",
    "days": 1,
    "travel_start_date": "2026-08-01",
    "travel_end_date": "2026-08-01",
    "attraction_preference": "历史古迹",
    "habit_preference": "不喜欢早起",
    "weather_forecast": [],
    "pois": [{"name": "玄武湖景区", "indoor": False}],
}

RECORD = {
    "trial_id": "trial-1",
    "case_id": "judge-case",
    "plan_generated": True,
    "status": "SUCCESS",
    "l0_codes": [],
    "route_by_day": [{
        "day": 1,
        "spots": [{"name": "玄武湖景区", "start": "10:00", "end": "12:00"}],
    }],
}


def _valid(judge_id: int = 1) -> dict:
    return {
        "preference_fit": 4,
        "pacing": 4,
        "geographic_coherence": 4,
        "time_realism": 4,
        "completeness": 5,
        "diversity_and_dining": 3,
        "evidence": {name: ["Day1 玄武湖景区"] for name in judge.DIMENSIONS},
        "reasons": {name: "reason" for name in judge.DIMENSIONS},
        "flags": [],
        "overall_comment": "ok",
    }


def test_payload_is_blind_to_labels_and_status():
    payload = judge.build_payload(CASE, RECORD)

    assert judge.FORBIDDEN_PAYLOAD_KEYS & set(payload) == set()
    assert "status" not in payload
    assert "l0_codes" not in payload
    assert payload["route"][0]["spots"][0]["name"] == "玄武湖景区"
    assert payload["scope"] == {
        "meals": False,
        "transport_legs": False,
        "live_info": False,
    }


def test_stub_provider_is_deterministic_and_weighted(tmp_path):
    first = judge.score_record(CASE, RECORD, provider="stub", k=2, cache_dir=tmp_path)
    second = judge.score_record(CASE, RECORD, provider="stub", k=2, cache_dir=tmp_path)

    assert first["overall_mean"] == second["overall_mean"]
    assert 0 <= first["overall_mean"] <= 100
    assert first["agreement"]["quadratic_weighted_kappa"] is not None


def test_cache_hit_avoids_second_judge_call(tmp_path):
    calls: list[int] = []

    def fake(payload, judge_id=1):
        calls.append(judge_id)
        return _valid(judge_id)

    first = judge.score_record(
        CASE, RECORD, provider="stub", k=1, cache_dir=tmp_path, judge_fn=fake,
    )
    second = judge.score_record(
        CASE, RECORD, provider="stub", k=1, cache_dir=tmp_path, judge_fn=fake,
    )

    assert len(calls) == 1
    assert first["cache_hits"] == 0
    assert second["cache_hits"] == 1
    assert second["judge_calls"] == 0


def test_replay_reads_cache_and_reports_cache_miss(tmp_path):
    def fake(payload, judge_id=1):
        return _valid(judge_id)

    # 用 llm provider + fake client 写入 runtime 缓存，不发真实请求。
    judge.score_record(
        CASE, RECORD, provider="llm", k=1, cache_dir=tmp_path, judge_fn=fake,
    )

    replay = judge.score_record(CASE, RECORD, provider="replay", k=1, cache_dir=tmp_path)
    assert replay["cache_hits"] == 1
    assert replay["overall_mean"] is not None

    missing = judge.score_record(
        CASE, RECORD, provider="replay", k=1, cache_dir=tmp_path / "empty",
    )
    assert "cache_miss" in missing["error"]
    assert missing["judges"] == []


def test_judge_budget_is_a_hard_limit(tmp_path):
    budget = judge.JudgeBudget(1)

    with pytest.raises(judge.JudgeBudgetExceeded):
        judge.score_record(
            CASE, RECORD, provider="stub", k=2, cache_dir=tmp_path, budget=budget,
        )


def test_malformed_judge_output_becomes_error_not_crash(tmp_path):
    def bad(payload, judge_id=1):
        data = _valid(judge_id)
        data["pacing"] = 9
        return data

    result = judge.score_record(
        CASE, RECORD, provider="stub", k=1, cache_dir=tmp_path, judge_fn=bad,
    )

    assert result["error"]
    assert "invalid_response" in result["error"]
    assert result["judges"] == []


def test_quadratic_weighted_kappa_known_cases():
    assert judge.quadratic_weighted_kappa([0, 1, 2], [0, 1, 2]) == 1.0
    assert judge.quadratic_weighted_kappa([0, 5], [5, 0]) < 0


def test_normalize_flags_maps_free_text_and_recomputes_evidence_missing():
    flags = judge.normalize_flags(
        ["连续雨天影响", "缺少餐饮安排", "景点分散", "unknown_text"],
        evidence={},
        reasons={name: "reason" for name in judge.DIMENSIONS},
    )

    assert "bad_weather_all_days" in flags
    assert "missing_dining" in flags
    assert "geographic_inefficiency" in flags
    assert "other" in flags
    assert "evidence_missing" not in flags
    assert set(flags) <= judge.CANONICAL_FLAGS

    missing = judge.normalize_flags([], evidence={}, reasons={})
    assert "evidence_missing" in missing


def test_agreement_counts_exact_and_within_one():
    result = judge.agreement([
        {name: 4 for name in judge.DIMENSIONS},
        {**{name: 4 for name in judge.DIMENSIONS}, "pacing": 5},
    ])

    assert result["exact"] == 5
    assert result["within_one"] == 6
    assert result["exact_rate"] == 0.8333


def test_summarize_reports_na_when_nothing_scored():
    summary = judge.summarize([{
        "target_id": "x",
        "case_id": "c",
        "judge": {"skipped": True, "reason": "not_delivered"},
    }])

    assert summary["scored"] == 0
    assert summary["overall_mean"] is None
    assert summary["coverage"] == 0.0


def test_summarize_pools_dimension_pairs_for_kappa():
    scores = {name: 4 for name in judge.DIMENSIONS}
    block = {
        "overall_mean": 80.0,
        "dimension_mean": scores,
        "judges": [{"scores": scores}, {"scores": scores}],
        "judge_calls": 0,
        "judge_tokens_est": 0,
        "cache_hits": 2,
    }
    summary = judge.summarize([{"target_id": "a", "case_id": "c", "judge": block}])

    assert summary["kappa_pooled"] == 1.0


def test_calibration_reports_mae_and_spearman():
    results = [
        {"target_id": "a", "judge": {"overall_mean": 80}},
        {"target_id": "b", "judge": {"overall_mean": 60}},
    ]
    report = judge.calibration_report(results, {"a": 75, "b": 70})

    assert report["n"] == 2
    assert report["mae"] == 7.5
    assert report["spearman"] == 1.0
    assert report["band_agreement"] == 0.5


def test_calibration_is_na_with_insufficient_labels():
    report = judge.calibration_report(
        [{"target_id": "a", "judge": {"overall_mean": 80}}], {"a": 75},
    )

    assert report["mae"] is None
    assert report["spearman"] is None