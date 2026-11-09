"""四臂策略回放、自适应跳过与 harness 第四模式。"""

from __future__ import annotations

from datetime import date

from app.planning.schemas import TravelPlanState

from tests.eval import adaptive_review, harness, production_policy


def _clean_state() -> TravelPlanState:
    return TravelPlanState(
        query="南京一日，上午看展，下午逛湖",
        destination="南京",
        travel_start_date=date(2026, 8, 1),
        travel_end_date=date(2026, 8, 1),
        days=1,
        max_per_day=3,
        pois=[
            {"name": "南京博物院", "indoor": True, "location": {"lng": 118.79, "lat": 32.04}},
            {"name": "玄武湖景区", "indoor": False, "location": {"lng": 118.80, "lat": 32.07}},
        ],
        route=[{"day": 1, "spots": [
            {"name": "南京博物院", "start_time": "09:30", "end_time": "11:30"},
            {"name": "玄武湖景区", "start_time": "14:00", "end_time": "16:00"},
        ]}],
    )


# ─── harness 第四模式 ───────────────────────────────────────

def test_risk_gate_mode_runs_the_real_gate_and_is_not_a_default_arm():
    state = _clean_state()
    counts: dict[str, int] = {}
    app = harness.build_evaluation_graph(
        "planner_risk_gate",
        planner=lambda _state: {"review_round": 1},
        reviewer=lambda _state: {"approved": True, "reviewer_issues": []},
        time_check=lambda _state: {"time_check_done": True},
        counts=counts,
    )
    app.invoke(state, config={"recursion_limit": 12})

    assert counts.get("risk_gate") == 1
    assert counts.get("planner") == 1
    assert harness.effective_mode(counts) == "planner_risk_gate"
    # 新增模式不得进入默认矩阵，否则会改变既有分母
    assert "planner_risk_gate" not in harness.EVALUATION_MODES
    assert "planner_risk_gate" in harness.POLICY_MODES


# ─── 门控判定 ──────────────────────────────────────────────

def test_gate_verdict_records_flags_and_skip_flag():
    verdict = production_policy.gate_verdict(_clean_state())

    assert set(verdict) == {"review_required", "time_check_required", "review_skipped", "flags"}
    assert isinstance(verdict["flags"], list)
    assert verdict["review_skipped"] is (not verdict["review_required"] and not verdict["time_check_required"])


# ─── ESR 定义 ──────────────────────────────────────────────

def _record(**overrides):
    base = {
        "plan_generated": True,
        "l0_codes": [],
        "l1_codes": [],
        "benchmark_label": "MATCH",
        "actual_outcome": "SUCCESS",
        "expected_feasible": True,
        "input_tokens_est": 100,
        "output_tokens_est": 50,
        "latency_s": 10.0,
        "status": "SUCCESS",
    }
    base.update(overrides)
    return base


def test_esr_rejects_partial_and_accepts_correct_reject_for_infeasible():
    assert production_policy.esr_success(_record()) is True
    assert production_policy.esr_success(_record(benchmark_label="WRONG_ACCEPT")) is False
    assert production_policy.esr_success(
        _record(l1_codes=["physical_time_deadlock"])
    ) is False
    assert production_policy.esr_success(
        _record(plan_generated=False, actual_outcome="CORRECT_REJECT", expected_feasible=False)
    ) is True
    assert production_policy.esr_success(
        _record(plan_generated=False, actual_outcome="SUCCESS", expected_feasible=False)
    ) is False


def test_attribution_uses_observable_fields():
    cases = {
        "c1": {
            "planner_reviewer": {
                "planning_revision_rounds": 1,
                "first_draft_l0": ["unknown_poi"],
                "l0_codes": [],
            },
        },
        "c2": {
            "planner_reviewer": {
                "planning_revision_rounds": 2,
                "first_draft_l0": [],
                "l0_codes": [],
            },
        },
    }
    report = production_policy.attribution(cases)

    assert report["rework_trials"] == 2
    assert report["rule_fixed"] == 1
    assert report["semantic_only"] == 1
    assert report["rule_ineffective"] == 0


# ─── 自适应跳过 ────────────────────────────────────────────

def _draft_row(**overrides):
    base = {
        "draft_id": "d1",
        "case_id": "c1",
        "source": "trial",
        "l0_known": True,
        "l0_codes": [],
        "l1_codes": [],
        "review_increment": 200,
        "verdicts": {
            True: {"review_skipped": True},
            False: {"review_skipped": True},
        },
    }
    base.update(overrides)
    return base


def test_policy_counts_skips_and_counterfactual_savings():
    rows = [
        _draft_row(draft_id="d1", review_increment=200),
        _draft_row(
            draft_id="d2",
            review_increment=100,
            verdicts={True: {"review_skipped": False}, False: {"review_skipped": True}},
        ),
    ]
    current = adaptive_review._policy(rows, True)
    relaxed = adaptive_review._policy(rows, False)

    assert current["skipped"] == 1
    assert relaxed["skipped"] == 2
    assert current["token_saved_counterfactual"] == 200
    assert relaxed["token_saved_counterfactual"] == 300
    assert current["false_skip"] == 0


def test_false_skip_is_detected_when_draft_keeps_a_defect():
    rows = [_draft_row(l0_codes=["unknown_poi"])]
    report = adaptive_review._policy(rows, True)

    assert report["false_skip"] == 1
    assert report["false_skip_rate"] == 1.0


def test_unknown_defects_are_not_counted_as_false_skip():
    # checkpoint 草稿没有 l0_codes，不能因为“看起来正常”就算安全
    rows = [_draft_row(l0_known=False, l0_codes=None, l1_codes=None)]
    report = adaptive_review._policy(rows, True)

    assert report["skipped"] == 1
    assert report["false_skip"] == 0
    assert report["defect_known"] == 0


def test_skipped_defect_counts_ignore_drafts_without_codes():
    rows = [
        _draft_row(draft_id="d1", l0_codes=["unknown_poi"], l1_codes=["opening_time_conflict"]),
        _draft_row(draft_id="d2", l0_known=False, l0_codes=None, l1_codes=None),
    ]
    report = adaptive_review._policy(rows, True)

    assert report["skipped"] == 2
    assert report["skipped_defect_counts"] == {
        "opening_time_conflict": 1,
        "unknown_poi": 1,
    }
    assert report["skipped_defect_total"] == 2
