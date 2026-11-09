"""并发通路校验基准：串行 vs 并发的调度属性。"""

from __future__ import annotations

from tests.eval import route_benchmark


def test_build_state_produces_expected_leg_count():
    state = route_benchmark.build_state(6)

    assert len(state.route[0]["spots"]) == 7
    assert len(state.pois) == 7


def test_concurrent_beats_serial_and_stays_within_worker_ceiling():
    row = route_benchmark.measure(legs=4, delay_ms=30, repeats=1)

    assert row["verified_legs"] == 4
    assert 1 < row["speedup"] <= row["max_workers"]
    # 串行至少要花 N × delay
    assert row["serial_p50_ms"] >= 4 * 30 * 0.8


def test_self_check_flags_structural_divergence():
    rows = [
        {"legs": 8, "speedup": 7.0},
        {"legs": 8, "speedup": 7.1},
        {"legs": 4, "speedup": 3.6},
    ]
    check = route_benchmark.self_check(rows)

    assert check["passed"] is True
    assert check["speedup_spread_by_legs"]["8"] == 0.1

    diverged = route_benchmark.self_check([
        {"legs": 8, "speedup": 7.0},
        {"legs": 8, "speedup": 2.0},
    ])
    assert diverged["passed"] is False
