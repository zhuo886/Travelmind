"""评测口径的分类与分母规则回归。"""

from __future__ import annotations

import json

from tests.eval.aggregate_trials import merge_judge
from tests.eval.metrics import aggregate, classify_trial, render_markdown


def _record(**overrides):
    base = {
        "case_id": "case",
        "mode_requested": "planner_only",
        "plan_generated": True,
        "status": "SUCCESS",
        "hard_pass": True,
        "l0_codes": [],
        "first_draft_l0": [],
        "planning_revision_rounds": 0,
        "invalid_trial": False,
        "error_kind": None,
        "failure_codes": [],
        "latency_s": 1.0,
        "soft_score": 80.0,
        "oor": {"outside": 0, "total": 10},
    }
    base.update(overrides)
    return base


BENCH_SUCCESS = {"allowed_outcomes": ["SUCCESS", "SUCCESS_WITH_WARNINGS"]}
BENCH_NEGATIVE = {"allowed_outcomes": ["PARTIAL", "CORRECT_REJECT"], "must_visit": []}


def test_correct_reject_requires_no_plan_and_explicit_reason():
    no_plan = classify_trial(
        _record(plan_generated=False, status="FAILED", hard_pass=False,
                failure_codes=["candidate_pool_preference_conflict"]),
        BENCH_NEGATIVE,
    )
    assert no_plan["actual_outcome"] == "CORRECT_REJECT"
    assert no_plan["benchmark_label"] == "MATCH"

    # 生成了违反硬约束的路线，不算"正确拒绝"。
    hard = classify_trial(
        _record(plan_generated=True, hard_pass=False, l0_codes=["unknown_poi"]),
        BENCH_NEGATIVE,
    )
    assert hard["actual_outcome"] == "HARD_FAIL"
    assert hard["benchmark_label"] == "HARD_FAIL"


def test_wrong_accept_is_only_a_benchmark_label():
    record = classify_trial(_record(plan_generated=True, hard_pass=True), BENCH_NEGATIVE)
    assert record["actual_outcome"] == "SUCCESS"
    assert record["benchmark_label"] == "WRONG_ACCEPT"
    assert record["expected_outcome_match"] is False


def test_over_reject_when_expected_success_but_no_plan():
    record = classify_trial(
        _record(plan_generated=False, status="FAILED", hard_pass=False), BENCH_SUCCESS,
    )
    assert record["actual_outcome"] == "FAILED"
    assert record["benchmark_label"] == "OVER_REJECT"


def test_infra_failure_stays_in_effective_denominator_but_not_hpr():
    records = [
        classify_trial(_record(), BENCH_SUCCESS),
        classify_trial(
            _record(plan_generated=False, status="FAILED", hard_pass=False, error_kind="infra"),
            BENCH_SUCCESS,
        ),
        classify_trial(_record(invalid_trial=True, invalid_reason="mode_mismatch"), BENCH_SUCCESS),
    ]
    summary = aggregate(records)

    assert summary["total_trials"] == 3
    assert summary["invalid_trials"] == 1
    assert summary["effective_trials"] == 2
    assert summary["fdr"] == {"num": 1, "den": 2, "value": 0.5}
    assert summary["hpr"] == {"num": 1, "den": 1, "value": 1.0}
    assert summary["invalid_rate"]["value"] == 0.3333


def test_rework_recovery_uses_first_draft_and_final_delivered():
    records = [
        classify_trial(_record(first_draft_l0=["unknown_poi"], l0_codes=[],
                               planning_revision_rounds=1), BENCH_SUCCESS),
        classify_trial(_record(first_draft_l0=["unknown_poi"], l0_codes=["unknown_poi"],
                               hard_pass=False, planning_revision_rounds=1), BENCH_SUCCESS),
        # 首版就通过的不进入返工分母。
        classify_trial(_record(first_draft_l0=[], l0_codes=[]), BENCH_SUCCESS),
    ]
    summary = aggregate(records)

    assert summary["rrr"] == {"num": 1, "den": 2, "value": 0.5}


def test_must_visit_denominator_counts_no_plan_trials():
    records = [
        classify_trial(_record(must_visit_expected=["玄武湖景区"], must_visit_ok=True), BENCH_SUCCESS),
        classify_trial(_record(plan_generated=False, status="FAILED", hard_pass=False,
                               must_visit_expected=["玄武湖景区"], must_visit_ok=False), BENCH_SUCCESS),
    ]
    summary = aggregate(records)

    assert summary["msr"] == {"num": 1, "den": 2, "value": 0.5}
    assert summary["mar"]["value"] is None


def test_pass_at_k_is_grouped_by_case_and_mode():
    records = [
        classify_trial(_record(case_id="c", mode_requested="planner_only"), BENCH_SUCCESS),
        classify_trial(_record(
            case_id="c", mode_requested="planner_only",
            plan_generated=False, status="FAILED", hard_pass=False,
        ), BENCH_SUCCESS),
    ]
    bucket = aggregate(records)["pass_at_k_by_case_mode"]["c__planner_only"]

    assert bucket == {
        "k": 2,
        "match": 1,
        "pass_at_k": True,
        "pass_pow_k": False,
        "hpr_pass_at_k": True,
    }


def test_expectations_aggregation_counts_violations_and_trials():
    records = [
        classify_trial(_record(
            expectations_evaluated=True,
            expectation_violations=[{"rule": "outdoor_on_bad_day_max"}],
        ), BENCH_SUCCESS),
        classify_trial(_record(
            expectations_evaluated=True, expectation_violations=[],
        ), BENCH_SUCCESS),
    ]
    summary = aggregate(records)

    assert summary["expectations"] == {
        "evaluated_trials": 2,
        "violations": 1,
        "trials_with_violations": 1,
        "by_rule": {"outdoor_on_bad_day_max": 1},
    }


def test_denominator_basis_switches_to_delivered_plan_for_v3():
    summary = aggregate([
        classify_trial(_record(delivered_plan=True, draft_generated=True), BENCH_SUCCESS),
    ])

    assert summary["denominator_basis"] == "delivered_plan"


def test_judge_block_is_aggregated_without_touching_other_metrics():
    judge = {
        "overall_mean": 70.0,
        "dimension_mean": {"pacing": 3.0},
        "agreement": {"quadratic_weighted_kappa": 0.5},
        "low_score_dimensions": ["pacing"],
        "error": None,
    }
    summary = aggregate([
        classify_trial(_record(judge=judge), BENCH_SUCCESS),
        classify_trial(_record(judge={"skipped": True}), BENCH_SUCCESS),
    ])

    assert summary["judge"]["scored_trials"] == 1
    assert summary["judge"]["overall_mean"] == 70.0
    assert summary["judge"]["coverage"] == {"num": 1, "den": 2, "value": 0.5}
    assert summary["judge"]["kappa_mean"] == 0.5


def test_merge_judge_maps_by_trial_id_without_mutating_files(tmp_path):
    (tmp_path / "judge_t1.json").write_text(
        json.dumps({"trial_id": "t1", "judge": {"overall_mean": 88.0}}),
        encoding="utf-8",
    )
    records = [{"trial_id": "t1"}, {"trial_id": "t2"}]

    merged = merge_judge(records, tmp_path)

    assert merged[0]["judge"]["overall_mean"] == 88.0
    assert "judge" not in merged[1]
    assert not list(tmp_path.glob("trial_*.json"))


def test_render_markdown_includes_v3_sections_when_data_exists():
    records = [
        classify_trial(_record(
            case_id="c", mode_requested="planner_only", expected_feasible=False,
            plan_generated=False, status="FAILED", hard_pass=False,
            failure_codes=["candidate_pool_preference_conflict"],
        ), {"allowed_outcomes": ["CORRECT_REJECT"], "expected_feasible": False}),
        classify_trial(_record(
            case_id="c", mode_requested="planner_only", expected_feasible=True,
        ), BENCH_SUCCESS),
    ]
    report = render_markdown(aggregate(records))

    assert "## 安全" in report
    assert "## Pass@K" in report
    assert "分母口径：plan_generated" in report
