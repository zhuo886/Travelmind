"""trial 产物必须自带 LLM 开关快照。

背景：2026-11-08 做思考链开关的 A/B 时，历史 trial 只记录了模型名，无法事后判断
某批运行到底有没有开思考链，导致对比结论只能靠延迟反推。这里把开关固化进产物。
"""

from tests.eval import run_trials


def test_snapshot_reads_thinking_switches(monkeypatch):
    monkeypatch.setenv("OPENAI_THINKING", "disabled")
    monkeypatch.setenv("OPENAI_THINKING_PLANNER", "disabled")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "4000")
    monkeypatch.setenv("OPENAI_STRUCTURED_METHOD", "json_mode")

    config = run_trials._llm_config_snapshot()

    assert config["thinking_global"] == "disabled"
    assert config["thinking_planner"] is False
    assert config["max_tokens"] == "4000"
    assert config["structured_method"] == "json_mode"


def test_planner_thinking_reported_as_enabled(monkeypatch):
    monkeypatch.setenv("OPENAI_THINKING", "disabled")
    monkeypatch.setenv("OPENAI_THINKING_PLANNER", "enabled")

    config = run_trials._llm_config_snapshot()

    assert config["thinking_global"] == "disabled"
    assert config["thinking_planner"] is True


def test_snapshot_always_reports_a_boolean(monkeypatch):
    """无论 .env.local 怎么配，快照里的 planner 开关都必须是布尔值，便于聚合。"""
    monkeypatch.delenv("OPENAI_THINKING_PLANNER", raising=False)

    assert isinstance(run_trials._llm_config_snapshot()["thinking_planner"], bool)
