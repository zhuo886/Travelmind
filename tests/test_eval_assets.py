"""评测资产版本、继承与冻结指纹回归。"""

from __future__ import annotations

from tests.eval import assets, harness


def test_v3_inherits_v2_and_adds_safety_cases():
    cases = harness.load_cases(version="v3")
    ids = [case["id"] for case in cases]

    assert len(cases) == 14
    assert len(ids) == len(set(ids))
    assert sum(1 for case in cases if case.get("fixture_dir") == "fixtures_v2") == 10
    # v3 自带 4 个安全负样本：室内空池、物理时间、营业时间、池内无此景点
    assert sum(1 for case in cases if case.get("fixture_dir") == "fixtures_v3") == 4


def test_v3_benchmark_hashes_match_actual_fixtures():
    assert assets.validate_version("v3") == []


def test_v1_v2_assets_are_frozen():
    assert assets.frozen_mismatches() == []


def test_v3_marks_exactly_four_infeasible_cases():
    benchmark = harness.load_benchmark("v3")
    infeasible = [
        case_id for case_id, case in benchmark.items()
        if case.get("expected_feasible") is False
    ]

    assert sorted(infeasible) == [
        "nanjing-1d-night-closed-negative",
        "sanya-1d-indooronly-empty-pool-negative",
        "shanghai-1d-twohour-three-must-negative",
        "shanghai-1d-unavailable-poi-negative",
    ]
    for case in benchmark.values():
        assert "expected_feasible" in case
        assert case.get("fixture_sha256")


def test_manifest_records_benchmark_and_fixture_hashes():
    manifest = assets.version_manifest("v3")

    assert manifest["version"] == "v3"
    assert manifest["benchmark"]["sha256"]
    assert len(manifest["fixtures"]) == 14
    assert all(item["sha256"] for item in manifest["fixtures"].values())