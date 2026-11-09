"""SSE 转发层时序与顺序不变量。"""

from __future__ import annotations

from tests.eval import sse_timing


def test_run_once_produces_order_consistent_events():
    run = sse_timing.run_once(delay_ms=1.0)

    assert run["violations"] == []
    assert run["result_events"] == 1
    assert run["sequence_respected"] is True
    assert run["stages"] == len(sse_timing.CANONICAL_SEQUENCE)
    assert run["ttfe_ms"] >= 0


def test_summary_reports_zero_violations_and_full_compliance():
    summary = sse_timing.build_summary(repeats=2, delay_ms=1.0)

    assert summary["violations"] == []
    assert summary["order_compliance"] == 1.0
    assert summary["events_per_run"] == len(sse_timing.CANONICAL_SEQUENCE) * 2 + 1
    assert summary["total_p50_ms"] >= summary["ttfe_p50_ms"]


def test_http_probe_validates_sse_framing_end_to_end():
    probe = sse_timing.http_probe()

    assert probe["status_code"] == 200
    assert probe["events"] >= 4
    assert probe["result_unique"] is True
    assert probe["result_last"] is True
    # TestClient 缓冲响应，所以这里不能声称测到了 TTFE
    assert "缓冲" in probe["note"]


def test_unknown_node_is_filtered_instead_of_emitted():
    run = sse_timing.run_once(
        delay_ms=0.0,
        sequence=("intent", "not_a_real_node"),
    )

    # 未挂文案的节点会被 run_stream 直接丢弃，不会产生半成品事件
    assert run["stages"] == 1
    assert run["violations"] == []


def test_unlabelled_graph_node_is_recorded_explicitly():
    import app.planning.graph as graph_module

    for node in sse_timing.UNLABELLED_GRAPH_NODES:
        assert node not in graph_module._NODE_LABELS
    for node in sse_timing.CANONICAL_SEQUENCE:
        assert node in graph_module._NODE_LABELS
