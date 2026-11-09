"""Checkpoint 修改的输入预算精算：两臂 prompt 真实捕获。"""

from __future__ import annotations

from pathlib import Path

from tests.eval import harness, modify_budget


def _case(case_id: str = "shanghai-1d-sunny-nightlife") -> dict:
    return next(case for case in harness.load_cases(version="v2") if case["id"] == case_id)


def _checkpoint(case: dict) -> dict:
    checkpoint = dict(case)
    checkpoint["route"] = [{
        "day": 1,
        "spots": [
            {"name": "外滩", "period": "afternoon", "start_time": "16:00", "end_time": "18:00"},
            {"name": "南京路步行街", "period": "evening", "start_time": "19:00", "end_time": "21:00"},
        ],
    }]
    return checkpoint


def test_full_plan_entry_has_more_calls_than_modify_entry():
    case = _case()
    row = modify_budget.measure_entry_prompts(case, _checkpoint(case))

    assert "IntentExtraction" in row["a_nodes"]
    assert "TravelRoute" in row["a_nodes"]
    assert row["b_nodes"] == ["TravelRoute"]
    assert row["a_llm_calls"] > row["b_llm_calls"]
    assert row["a_tokens"] > 0 and row["b_tokens"] > 0


def test_modify_prompt_carries_previous_route_so_tokens_are_not_free():
    case = _case()
    with_route = modify_budget.measure_entry_prompts(case, _checkpoint(case))
    without_route = modify_budget.measure_entry_prompts(case, None)

    # B 臂必须把上一版路线算进去，否则会低估成本
    assert with_route["b_tokens"] > 0
    assert without_route["b_calls"] == []


def test_e2_reference_is_loaded_and_labelled():
    reference = modify_budget.load_e2_reference()

    assert reference is not None
    assert reference["mode"] == "planner_only"
    assert "同子图" in reference["note"]


def test_node_token_table_groups_by_arm_and_schema():
    rows = [{
        "a_calls": [{"schema": "TravelRoute", "tokens": 100}],
        "b_calls": [{"schema": "TravelRoute", "tokens": 120}],
    }]
    table = modify_budget.node_token_table(rows)

    assert table["A:TravelRoute"] == [100]
    assert table["B:TravelRoute"] == [120]


def test_latency_is_a_partial_decomposition_not_a_full_p50():
    summary = modify_budget.build_summary([])

    assert summary["latency"]["status"] == "partial_decomposition"
    assert summary["latency"]["full_chain_status"] == "not_measured"
    assert "伪造" in summary["latency"]["reason"]

    decomposition = summary["latency"]["decomposition"]
    assert decomposition["arm_a"]["coverage"] < 1.0
    assert set(decomposition["arm_a"]["measured"]) == {"planner", "reviewer", "time_check"}
    # 未测阶段必须标 N/A，不能用 0% 冒充
    assert decomposition["stages"]["retrieval"]["share"] is None
    assert decomposition["stages"]["planning"]["share"] is not None
    assert Path("evaluation/checkpoint_benchmark/summary.json").exists()


def test_stage_buckets_cover_every_arm_node():
    covered = {node for nodes in modify_budget.STAGE_NODES.values() for node in nodes}

    assert set(modify_budget.ARM_A_NODES) == covered
    assert set(modify_budget.ARM_B_NODES) <= covered
