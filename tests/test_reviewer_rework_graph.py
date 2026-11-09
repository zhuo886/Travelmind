"""planner ⇄ reviewer 返工闭环与 max_review_rounds 上限回归。"""

from datetime import date

from app.planning.schemas import TravelPlanState


def _install_graph_mocks(monkeypatch, calls, *, always_reject=False):
    import app.planning.graph as graph_module

    monkeypatch.setattr(graph_module, "make_intent_node", lambda *a, **k: lambda state: {
        "destination": "南京",
        "travel_start_date": date(2026, 11, 6),
        "travel_end_date": date(2026, 11, 6),
        "days": 1,
        "missing_fields": [],
    })
    monkeypatch.setattr(graph_module, "make_query_rewrite_node", lambda *a, **k: lambda state: {
        "rewritten_query": state.query,
    })
    monkeypatch.setattr(graph_module, "weather_search_node", lambda state: {
        "weather_forecast": [], "weather_note": "mock",
    })
    monkeypatch.setattr(graph_module, "attraction_search_node", lambda state: {
        "pois": [{"name": "A", "location": {"lat": 32, "lng": 118}}],
    })
    monkeypatch.setattr(graph_module, "make_candidate_react_node", lambda *a: lambda state: {
        "candidate_search_actions": [{"action": "stop"}],
    })
    monkeypatch.setattr(graph_module, "candidate_search_node", lambda state: {
        "candidate_search_round": 1,
    })
    monkeypatch.setattr(graph_module, "candidate_validator_node", lambda state: {
        "candidate_pool_status": "ok",
    })
    monkeypatch.setattr(graph_module, "route_after_candidate_validation", lambda state: "planner")

    def planner_factory(*args, **kwargs):
        def planner(state):
            calls["planner"] += 1
            return {
                "route": [{"day": 1, "spots": [{"name": "A"}]}],
                "review_round": state.review_round + 1,
            }
        return planner

    monkeypatch.setattr(graph_module, "make_planner_node", planner_factory)
    monkeypatch.setattr(graph_module, "route_distance_check_node", lambda state: {})
    monkeypatch.setattr(graph_module, "route_risk_gate_node", lambda state: {
        "review_required": True,
        "time_check_required": False,
        "review_skipped": False,
    })
    monkeypatch.setattr(graph_module, "record_route_snapshot_node", lambda state: {})
    monkeypatch.setattr(graph_module, "main_meal_candidate_search_node", lambda state: {
        "main_meal_candidates": [], "main_meal_status": "ok",
    })

    def reviewer_factory(*args, **kwargs):
        def reviewer(state):
            calls["reviewer"] += 1
            approved = not always_reject and calls["reviewer"] >= 2
            return {
                "approved": approved,
                "reviewer_issues": [] if approved else ["需要调整路线"],
                "route_modify_opinion": None if approved else "调整路线",
            }
        return reviewer

    monkeypatch.setattr(graph_module, "make_reviewer_node", reviewer_factory)
    monkeypatch.setattr(graph_module, "make_time_check_node", lambda *a, **k: lambda state: {
        "time_check_done": True,
        "time_violations": [],
        "time_check_round": state.time_check_round + 1,
    })
    monkeypatch.setattr(graph_module, "main_meal_output_node", lambda state: {"meal_slots": []})
    monkeypatch.setattr(graph_module, "make_spot_tips_node", lambda *a, **k: lambda state: {"spot_tips": {}})

    def finalize_factory(*args, **kwargs):
        def finalize(state):
            calls["finalize"] += 1
            return {"final_plan": {"days": []}}
        return finalize

    monkeypatch.setattr(graph_module, "make_finalize_node", finalize_factory)


def test_reviewer_reworks_once_then_approves(monkeypatch):
    calls = {"planner": 0, "reviewer": 0, "finalize": 0}
    _install_graph_mocks(monkeypatch, calls)
    import app.planning.graph as graph_module

    result = graph_module.build_graph().invoke(
        TravelPlanState(query="南京一日游", max_review_rounds=1),
        config={"recursion_limit": 40},
    )

    assert result["final_plan"] == {"days": []}
    assert calls == {"planner": 2, "reviewer": 2, "finalize": 1}


def test_reviewer_rework_is_capped_by_max_review_rounds(monkeypatch):
    calls = {"planner": 0, "reviewer": 0, "finalize": 0}
    _install_graph_mocks(monkeypatch, calls, always_reject=True)
    import app.planning.graph as graph_module

    result = graph_module.build_graph().invoke(
        TravelPlanState(query="南京一日游", max_review_rounds=0),
        config={"recursion_limit": 40},
    )

    assert result["final_plan"] == {"days": []}
    assert calls == {"planner": 1, "reviewer": 1, "finalize": 1}
