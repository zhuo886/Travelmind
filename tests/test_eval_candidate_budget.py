"""有界 ReAct 合规、幻觉阻断与候选补查消融（离线）。"""

from __future__ import annotations

import json

from tests.eval import candidate_budget, gap_fill_ablation


def _record(**overrides):
    base = {
        "trial_id": "t1",
        "case_id": "c",
        "mode_requested": "planner_only",
        "invalid_trial": False,
        "error": None,
        "plan_generated": True,
        "candidate_api_calls": 3,
        "oor": {"outside": 0, "total": 5},
        "l0_codes": [],
        "l1_codes": [],
        "first_draft_l0": [],
        "must_visit_ok": True,
        "expected_feasible": True,
        "candidate_search_trace": [],
    }
    base.update(overrides)
    return base


def test_budget_report_flags_overrun_and_computes_rate():
    report = candidate_budget.budget_report([
        _record(),
        _record(trial_id="t2", candidate_api_calls=12),
    ])

    assert report["trials"] == 2
    assert report["compliant"] == 1
    assert report["compliance_rate"] == 0.5
    assert report["violations"][0]["candidate_api_calls"] == 12


def test_budget_is_na_when_no_trial_ever_searched():
    """harness 从 planner 起跑，candidate_api_calls 恒为 0：合规率是空转，必须标 N/A。"""
    report = candidate_budget.budget_report([_record(candidate_api_calls=0)])

    assert report["exercised"] is False
    assert report["compliance_rate"] is None
    assert "无法由这批数据证明" in report["reason"]


def test_hallucination_report_counts_poi_level_and_trial_level():
    report = candidate_budget.hallucination_report([
        _record(oor={"outside": 1, "total": 4}),
        _record(
            trial_id="t2", mode_requested="planner_reviewer",
            first_draft_l0=["unknown_poi"], l0_codes=[],
        ),
    ])

    assert report["oor"]["outside"] == 1
    assert report["oor"]["total"] == 9
    assert report["first_draft_unknown_poi"] == 1
    assert report["blocked_by_reviewer"] == 1


def test_dedupe_is_na_until_trace_is_persisted():
    report = candidate_budget.dedupe_report([_record()])

    assert report["available"] is False
    assert report["repeated_query_rejected"] is None
    assert "未落盘" in report["reason"]

    with_trace = candidate_budget.dedupe_report([
        _record(candidate_search_trace=[
            {"error_code": "REPEATED_QUERY"},
            {"cache_hit": True},
            {"error_code": None},
        ])
    ])
    assert with_trace["available"] is True
    assert with_trace["repeated_query_rejected"] == 1
    assert with_trace["cache_hits"] == 1


def test_gap_fill_scenarios_are_frozen_and_balanced():
    scenarios = gap_fill_ablation.load_scenarios()

    assert len(scenarios) == 28
    kinds = {}
    for scenario in scenarios:
        kinds[scenario["kind"]] = kinds.get(scenario["kind"], 0) + 1
    assert kinds == {"named": 7, "indoor": 7, "count": 7, "boundary": 7}


def test_named_gap_is_filled_by_bounded_react_but_not_by_seed_pool():
    scenario = next(
        item for item in gap_fill_ablation.load_scenarios() if item["kind"] == "named"
    )
    seed_only = gap_fill_ablation.run_arm(scenario, "seed_only")
    react = gap_fill_ablation.run_arm(scenario, "bounded_react")

    named_gaps = [gap for gap in seed_only["gaps_before"] if gap.startswith("named:")]
    assert named_gaps, "场景必须至少包含一个点名缺口"
    # 只靠种子池时点名缺口仍在，补查后才消失
    assert [gap for gap in seed_only["gaps_after"] if gap.startswith("named:")]
    assert not [gap for gap in react["gaps_after"] if gap.startswith("named:")]
    assert react["api_calls"] >= 1


def test_boundary_scenarios_never_invent_places():
    scenario = next(
        item for item in gap_fill_ablation.load_scenarios() if item["kind"] == "boundary"
    )
    react = gap_fill_ablation.run_arm(scenario, "bounded_react")

    assert react["fixed"] == []
    assert react["introduced"] == []


def test_must_visit_is_bucketed_so_v2_is_not_diluted():
    report = candidate_budget.must_visit_report([
        _record(_source="evaluation/trials/run-20261107-v2", must_visit_ok=True),
        _record(_source="evaluation/trials/run-20261106/s1", must_visit_ok=False),
        _record(_source="evaluation/trials/run-20261107-negative", must_visit_ok=True),
    ])

    assert report["evaluated"] == 3
    assert report["by_bucket"]["v2"] == {
        "evaluated": 1, "passed": 1, "failed_cases": [], "rate": 1.0,
    }
    assert report["by_bucket"]["v1"]["rate"] == 0.0
    assert report["by_bucket"]["negative"]["passed"] == 1


def test_safety_report_keeps_infeasible_samples_separate():
    report = candidate_budget.safety_report([
        _record(actual_outcome="CORRECT_REJECT", expected_feasible=False,
                plan_generated=False, must_visit_ok=False),
        _record(actual_outcome="CORRECT_REJECT", expected_feasible=False,
                plan_generated=False, must_visit_ok=None),
    ])

    assert report["trials"] == 2
    assert report["outcomes"] == {"CORRECT_REJECT": 2}
    assert report["must_visit_evaluated"] == 1
    # 不可行的 must_visit_ok=False 是正确拒绝的结果，不算覆盖失败
    assert "不算失败" in report["note"]


def test_scenario_budget_check_uses_real_executor_denominator(tmp_path):
    path = tmp_path / "gap_fill.json"
    path.write_text(json.dumps({
        "rows": [
            {"arm": "bounded_react", "api_calls": 2},
            {"arm": "bounded_react", "api_calls": 1},
            {"arm": "seed_only", "api_calls": 0},
        ]
    }), encoding="utf-8")

    check = candidate_budget.scenario_budget_check(path)

    assert check["scenarios"] == 2  # seed_only 不计入预算口径
    assert check["compliant"] == 2
    assert check["rate"] == 1.0
    assert check["max_calls"] == 2


def test_summary_reports_boundary_false_fix_as_zero(tmp_path):
    summary = gap_fill_ablation.build_summary()

    assert summary["scenarios"] == 28
    assert summary["boundary_false_fix"] == 0
    assert summary["bounded_react_fixable"]["fixed"] >= summary["seed_only_fixable"]["fixed"]
    assert summary["budget_max_calls"] <= candidate_budget.API_BUDGET_CEILING
    # 结果可序列化，便于落盘复核
    json.dumps(summary, ensure_ascii=False)
