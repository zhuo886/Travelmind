"""Reviewer 可靠性：proxy / snapshot_trace 双口径与受控挑战集。"""

from __future__ import annotations

import json

from app.planning.quality import hard_constraint_report

from tests.eval import harness, reviewer_challenge, reviewer_reliability


def _proxy_record(**overrides):
    base = {
        "mode_requested": "planner_reviewer",
        "planning_revision_rounds": 1,
        "first_draft_l0": ["unknown_poi"],
        "l0_codes": [],
        "l1_codes": [],
        "plan_generated": True,
        "status": "SUCCESS",
        "benchmark_label": "MATCH",
    }
    base.update(overrides)
    return base


def test_proxy_metrics_mark_ineffective_but_not_clean_block():
    report = reviewer_reliability.evaluate([
        _proxy_record(),
        _proxy_record(l0_codes=["unknown_poi"], status="FAILED", benchmark_label="HARD_FAIL"),
        _proxy_record(
            mode_requested="planner_only", planning_revision_rounds=0,
            first_draft_l0=[], benchmark_label="WRONG_ACCEPT",
            l0_codes=[], status="SUCCESS",
        ),
    ])
    proxy = report["by_source"]["proxy"]

    assert proxy["rework_events_with_first_l0"] == 2
    assert proxy["rework_effective"] == 1
    assert proxy["rework_ineffective"] == 1
    assert proxy["rework_effective_rate"]["value"] == 0.5
    assert proxy["clean_block"] is None
    assert proxy["rework_regression_rate"] is None
    assert proxy["wrong_accept"] == 1


def test_trace_metrics_effective_ignored_and_clean_block():
    effective_trace = [
        {
            "iteration": 1, "l0_codes": ["unknown_poi"], "l1_codes": [], "defect_count": 1,
            "reviewer_approved": False, "rework_requested": True,
            "route_signature": "a", "is_delivered": False,
        },
        {
            "iteration": 2, "l0_codes": [], "l1_codes": [], "defect_count": 0,
            "reviewer_approved": True, "rework_requested": False,
            "route_signature": "b", "is_delivered": True,
        },
    ]
    ignored_trace = [
        {
            "iteration": 1, "l0_codes": ["unknown_poi"], "l1_codes": [], "defect_count": 1,
            "reviewer_approved": False, "rework_requested": True,
            "route_signature": "a", "is_delivered": False,
        },
        {
            "iteration": 2, "l0_codes": ["unknown_poi"], "l1_codes": [], "defect_count": 1,
            "reviewer_approved": False, "rework_requested": True,
            "route_signature": "a", "is_delivered": False,
        },
    ]
    clean_block_trace = [{
        "iteration": 1, "l0_codes": [], "l1_codes": [], "defect_count": 0,
        "reviewer_approved": False, "rework_requested": True,
        "route_signature": "clean", "is_delivered": True,
    }]
    report = reviewer_reliability.evaluate([
        {"reviewer_calls": 1, "plan_generated": True, "delivered_plan": True,
         "snapshot_trace": effective_trace, "benchmark_label": "MATCH"},
        {"reviewer_calls": 1, "plan_generated": False, "delivered_plan": False,
         "snapshot_trace": ignored_trace, "benchmark_label": "HARD_FAIL"},
        {"reviewer_calls": 1, "plan_generated": False, "delivered_plan": False,
         "snapshot_trace": clean_block_trace, "benchmark_label": "MISMATCH"},
    ])
    trace = report["by_source"]["snapshot_trace"]

    assert trace["snapshots"] == 5
    assert trace["rework_events"] == 2
    assert trace["rework_effective"] == 1
    assert trace["rework_ignored"] == 1
    assert trace["clean_snapshots"] == 2
    assert trace["clean_block"] == 1
    assert trace["clean_block_rate"]["value"] == 0.5
    assert trace["delivered_trials"] == 1
    assert trace["review_request_rate"] == {"num": 4, "den": 5, "value": 0.8}


def test_sources_are_reported_separately():
    report = reviewer_reliability.evaluate([
        _proxy_record(),
        {
            "reviewer_calls": 1, "plan_generated": True, "delivered_plan": True,
            "snapshot_trace": [{
                "iteration": 1, "l0_codes": [], "l1_codes": [], "defect_count": 0,
                "reviewer_approved": True, "rework_requested": False,
                "route_signature": "x", "is_delivered": True,
            }],
        },
    ])

    assert report["by_source"]["proxy"]["trials"] == 1
    assert report["by_source"]["snapshot_trace"]["trials"] == 1


def _stub_reviewer(state):
    report = hard_constraint_report(state)
    problems = [item["message"] for item in (*report["l0"], *report["l1"])]
    return {
        "approved": not problems,
        "reviewer_issues": problems,
        "route_modify_opinion": "；".join(problems),
    }


def test_reviewer_challenge_assets_and_stub_metrics():
    challenges = reviewer_challenge.load_challenges()
    cases = {case["id"]: case for case in harness.load_cases(version="v2")}

    assert len(challenges) == 6
    assert all(challenge.get("base_fixture") in cases for challenge in challenges)

    summary = reviewer_challenge.evaluate(challenges, cases, _stub_reviewer, k=1)

    assert summary["defect_challenges"] == 5
    assert summary["clean_challenges"] == 1
    assert summary["detection_rate"]["value"] == 1.0
    assert summary["keyword_match_rate"]["value"] == 1.0
    assert summary["clean_block_rate"]["value"] == 0.0
    assert summary["consensus_accuracy"]["value"] == 1.0
    assert summary["consistency_rate"]["value"] == 1.0


def test_replay_summary_rebuilds_report_without_reviewer_calls(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({
        "provider": "llm",
        "model": "glm-test",
        "results": [{
            "challenge_id": "c",
            "expected_verdict": "reject",
            "injected_defect": "unknown_poi",
            "runs": [{
                "verdict": "reject", "expected": "reject", "correct": True,
                "keywords_hit": ["池外"], "keyword_match": True,
                "issues": ["路线包含候选池外景点"], "tokens_est": 10,
                "latency_s": 1.0, "error": None,
            }],
        }],
    }), encoding="utf-8")

    code = reviewer_challenge.main([
        "--replay-summary", str(summary_path), "--out", str(tmp_path / "out"),
    ])

    assert code == 0
    report = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert report["provider"] == "llm"
    assert report["model"] == "glm-test"
    assert report["detection_rate"]["value"] == 1.0