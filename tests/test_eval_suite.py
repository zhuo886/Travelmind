"""评测矩阵编排的参数回归：``--case`` 必须逐条重复。"""

from __future__ import annotations

import json
from pathlib import Path

from tests.eval import run_suite, run_trials


def test_stage_builds_repeated_case_flags(monkeypatch, tmp_path: Path):
    captured: dict[str, list[str]] = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(run_trials, "main", fake_main)
    out = run_suite._run_stage("s1", ["case-a", "case-b"], 1, tmp_path)

    assert out == tmp_path / "s1"
    assert captured["argv"].count("--case") == 2
    assert "case-a" in captured["argv"] and "case-b" in captured["argv"]
    assert "--allow-external-calls" in captured["argv"]
    assert "--skip-existing" in captured["argv"]


def test_chunks_splits_cases_evenly():
    from tests.eval.run_parallel import chunks

    assert chunks(["a", "b", "c", "d", "e"], 3) == [["a", "d"], ["b", "e"], ["c"]]
    assert chunks(["a"], 3) == [["a"]]


def test_check_s1_flags_invalid_and_missing_time_check(tmp_path: Path):
    record = {
        "case_id": "case-a",
        "mode_requested": "planner_reviewer_time_check",
        "nodes_entered": ["planner", "reviewer"],
        "invalid_trial": True,
        "invalid_reason": "time_check_not_executed",
    }
    (tmp_path / "trial_a.json").write_text(json.dumps(record), encoding="utf-8")

    problems = run_suite.check_s1(tmp_path)

    assert any("time_check_not_executed" in item for item in problems)
    assert any("C 组未执行 time_check" in item for item in problems)
    assert any("trial 数为 1" in item for item in problems)


def test_check_s1_passes_complete_matrix(tmp_path: Path):
    for case in run_suite.S1_CASES:
        for mode in ("planner_only", "planner_reviewer", "planner_reviewer_time_check"):
            nodes = ["planner", "snapshot_gate"]
            if mode != "planner_only":
                nodes.append("reviewer")
            if mode == "planner_reviewer_time_check":
                nodes.append("time_check")
            record = {
                "case_id": case,
                "mode_requested": mode,
                "nodes_entered": nodes,
                "invalid_trial": False,
            }
            (tmp_path / f"trial_{case}__{mode}.json").write_text(
                json.dumps(record), encoding="utf-8"
            )

    assert run_suite.check_s1(tmp_path) == []
