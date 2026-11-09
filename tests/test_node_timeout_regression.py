"""已知问题回归：节点预算到期必须终止卡住的节点。

2026-11-05 源项目真实联调记录：planner 末次模型调用耗时 182.7 秒，超过默认
150 秒节点预算，但本次执行未被节点超时终止；随后仅在 `.env.local` 把
`NODE_TIMEOUT_PLANNER_SECONDS` 调到 240 秒，问题本身未被确认修复。

本测试不修改超时实现，只锁定契约：节点预算到期后，事件流必须产出
`NODE_TIMEOUT`，而不是继续等待节点自然结束。
"""

import asyncio
import time

from app.core.agent_runs import AgentRunRegistry, node_timeout_seconds, observe_agent_events


def test_stuck_planner_is_terminated_at_node_budget(monkeypatch):
    import app.core.agent_runs as module

    monkeypatch.delenv("PLAN_TIMEOUT_SECONDS", raising=False)
    # node_timeout_seconds 会把环境变量钳制到最小 1 秒；这里直接注入 0.1 秒，
    # 让回归测试在毫秒级验证“预算到期即终止”的契约。
    monkeypatch.setattr(module, "node_timeout_seconds", lambda node: 0.1)
    registry = AgentRunRegistry()
    run_id = registry.start("owner", "plan")
    started = time.monotonic()

    async def source():
        yield {"type": "stage", "node": "planner", "label": "start"}
        await asyncio.sleep(0.3)
        yield {"type": "stage_summary", "node": "planner", "summary": "late"}
        yield {"type": "result", "success": True, "plan": {}}

    async def collect():
        return [event async for event in observe_agent_events(source(), run_id, registry=registry)]

    events = asyncio.run(collect())
    elapsed = time.monotonic() - started

    assert events[-1]["code"] == "NODE_TIMEOUT"
    assert events[-1]["node"] == "planner"
    assert elapsed < 0.3
    assert registry.status(run_id) == "timed_out"


def test_planner_within_budget_is_not_interrupted(monkeypatch):
    import app.core.agent_runs as module

    monkeypatch.delenv("PLAN_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(module, "node_timeout_seconds", lambda node: 0.5)
    registry = AgentRunRegistry()
    run_id = registry.start("owner", "plan")

    async def source():
        yield {"type": "stage", "node": "planner", "label": "start"}
        await asyncio.sleep(0.05)
        yield {"type": "stage_summary", "node": "planner", "summary": "done"}
        yield {"type": "result", "success": True, "plan": {}}

    async def collect():
        return [event async for event in observe_agent_events(source(), run_id, registry=registry)]

    events = asyncio.run(collect())

    assert events[-1]["type"] == "result"
    assert registry.status(run_id) == "succeeded"


def test_node_timeout_env_precedence_and_clamp(monkeypatch):
    monkeypatch.delenv("NODE_TIMEOUT_SECONDS", raising=False)

    monkeypatch.setenv("NODE_TIMEOUT_PLANNER_SECONDS", "240")
    assert node_timeout_seconds("planner") == 240.0

    monkeypatch.setenv("NODE_TIMEOUT_PLANNER_SECONDS", "0.01")
    assert node_timeout_seconds("planner") == 1.0

    monkeypatch.setenv("NODE_TIMEOUT_PLANNER_SECONDS", "2000")
    assert node_timeout_seconds("planner") == 900.0

    monkeypatch.delenv("NODE_TIMEOUT_PLANNER_SECONDS")
    assert node_timeout_seconds("planner") == 150.0
