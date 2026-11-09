"""planner⇄reviewer 轮次预算与“预算耗尽返回草稿”回归。"""

from __future__ import annotations

import asyncio

from langgraph.errors import GraphRecursionError

from app.planning.graph import (
    BUDGET_CUT_NOTE,
    _iter_graph_events,
    recursion_budget,
    salvage_partial_result,
)
from app.planning.schemas import TravelPlanState


def test_recursion_budget_covers_four_round_rework():
    """一轮 planner⇄reviewer 是 6 步；4 轮 + 收尾节点必须落在预算内。"""
    state = TravelPlanState(query="北京三日游", max_review_rounds=3, max_time_check_rounds=3)
    # 1 intent + 1 parallel rewrite + 1 attraction + 3 candidate + 4*6 review
    # + 3 time_check 收尾 + 1 meal/tips + 1 finalize ≈ 38 步
    assert recursion_budget(state) >= 38
    assert recursion_budget(state) > 2 * (state.max_review_rounds + 1) + 2 * state.max_time_check_rounds + 20


def test_recursion_budget_shrinks_with_fewer_rounds():
    few = TravelPlanState(query="x", max_review_rounds=1, max_time_check_rounds=1)
    many = TravelPlanState(query="x", max_review_rounds=4, max_time_check_rounds=2)
    assert recursion_budget(few) < recursion_budget(many)


def test_astream_budget_exhaustion_is_absorbed():
    """GraphRecursionError 不再穿透到上层，而是置位 flag 收束。"""

    class _FakeApp:
        def astream_events(self, init, config, version):
            async def gen():
                raise GraphRecursionError("Recursion limit of 34 reached")
                yield  # pragma: no cover

            return gen()

    flag = {"cut": False}

    async def collect():
        return [ev async for ev in _iter_graph_events(_FakeApp(), TravelPlanState(query="x"), {"recursion_limit": 1}, flag)]

    assert asyncio.run(collect()) == []
    assert flag["cut"] is True


def test_salvage_keeps_warning_without_route():
    acc = TravelPlanState(query="x").model_dump()
    partial = salvage_partial_result(acc, BUDGET_CUT_NOTE)
    assert BUDGET_CUT_NOTE in partial.warnings
