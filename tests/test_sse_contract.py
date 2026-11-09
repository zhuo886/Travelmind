"""SSE 事件契约：只断言关键节点与终帧，不依赖并行分支到达顺序。"""

import asyncio

import app.planning.graph as graph_module


def _event(kind, name, output=None):
    data = {} if output is None else {"output": output}
    return {"event": kind, "name": name, "data": data}


class _FakeGraph:
    async def astream_events(self, state, config=None, version="v2"):
        # 故意先发 weather_search 再发 query_rewrite，证明测试不要求固定顺序。
        yield _event("on_chain_start", "intent")
        yield _event("on_chain_end", "intent", {"destination": "杭州", "days": 1})
        yield _event("on_chain_start", "weather_search")
        yield _event("on_chain_end", "weather_search", {"weather_forecast": [], "weather_note": "mock"})
        yield _event("on_chain_start", "query_rewrite")
        yield _event("on_chain_end", "query_rewrite", {"rewritten_query": "杭州西湖慢游"})
        yield _event("on_chain_start", "unrelated_node")
        yield _event("on_chain_end", "unrelated_node", {"ignored": True})
        yield _event("on_chain_start", "finalize")
        yield _event("on_chain_end", "finalize", {"final_plan": {"days": []}})


class _FakeFinalizeDirectGraph:
    async def astream_events(self, state, config=None, version="v2"):
        yield _event("on_chain_start", "intent")
        yield _event("on_chain_end", "intent", {"destination": "杭州", "days": 1})
        yield _event("on_chain_start", "finalize_direct")
        yield _event("on_chain_end", "finalize_direct", {
            "final_plan": {"days": [{"day": 1, "timeline": []}]},
            "approved": True,
            "result_status": "SUCCESS_WITH_WARNINGS",
        })


def test_run_stream_emits_key_stage_events_without_fixed_parallel_order(monkeypatch):
    monkeypatch.setattr(graph_module, "build_graph", lambda *args, **kwargs: _FakeGraph())

    async def collect():
        return [event async for event in graph_module.run_stream("杭州一日，西湖边慢慢走")]

    events = asyncio.run(collect())
    stages = [event["node"] for event in events if event.get("type") == "stage"]
    summaries = [event["node"] for event in events if event.get("type") == "stage_summary"]

    assert stages[0] == "intent"
    assert {"intent", "query_rewrite", "weather_search", "finalize"} <= set(stages)
    assert {"intent", "query_rewrite", "weather_search", "finalize"} <= set(summaries)
    assert "unrelated_node" not in stages
    assert events[-1]["type"] == "result"
    assert "success" in events[-1]


def test_run_stream_merges_finalize_direct_plan_into_result(monkeypatch):
    """早停分支的 finalize_direct 必须进入 SSE 累积状态，不能返回空 days。"""
    monkeypatch.setattr(graph_module, "build_graph", lambda *args, **kwargs: _FakeFinalizeDirectGraph())

    async def collect():
        return [event async for event in graph_module.run_stream("杭州一日游")]

    events = asyncio.run(collect())
    stages = [event["node"] for event in events if event.get("type") == "stage"]

    assert "finalize_direct" in stages
    assert events[-1]["type"] == "result"
    assert events[-1]["success"] is True
    assert events[-1]["plan"]["days"] == [{"day": 1, "timeline": []}]
