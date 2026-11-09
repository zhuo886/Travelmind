"""结构化输出方法降级逻辑的离线回归。"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.openai import _StructuredOutputWithFallback, resolve_extra_body, resolve_max_tokens


class _Schema(BaseModel):
    ok: bool


def _raw():
    return SimpleNamespace(content="", response_metadata={"finish_reason": "tool_calls"}, tool_calls=[])


def test_thinking_switch_follows_env(monkeypatch):
    monkeypatch.delenv("OPENAI_THINKING", raising=False)
    assert resolve_extra_body() == {}
    monkeypatch.setenv("OPENAI_THINKING", "disabled")
    assert resolve_extra_body() == {"thinking": {"type": "disabled"}}


def test_explicit_thinking_override_beats_env(monkeypatch):
    """planner 单独开思考链时，显式 True 必须能覆盖全局 disabled。"""
    monkeypatch.setenv("OPENAI_THINKING", "disabled")
    assert resolve_extra_body(True) == {}
    assert resolve_extra_body(False) == {"thinking": {"type": "disabled"}}


def test_max_tokens_switch_follows_env(monkeypatch):
    monkeypatch.delenv("OPENAI_MAX_TOKENS", raising=False)
    assert resolve_max_tokens() is None
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "0")
    assert resolve_max_tokens() is None
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "8000")
    assert resolve_max_tokens() == 8000


class _Runnable:
    def __init__(self, *, parsed=None, error=None):
        self.parsed = parsed
        self.error = error
        self.calls = []

    def invoke(self, messages, **kwargs):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return {"raw": _raw(), "parsed": self.parsed, "parsing_error": None}


class _FakeLLM:
    model_name = "fake-model"

    def __init__(self, runnables):
        self.runnables = runnables
        self.methods = []

    def with_structured_output(self, schema, **kwargs):
        method = kwargs["method"]
        self.methods.append(method)
        return self.runnables[method]


def test_none_result_falls_back_to_json_mode_and_stays_preferred(monkeypatch):
    monkeypatch.setenv("OPENAI_STRUCTURED_METHOD", "function_calling")
    function_calling = _Runnable(parsed=None)
    json_mode = _Runnable(parsed=_Schema(ok=True))
    fake = _FakeLLM({"function_calling": function_calling, "json_mode": json_mode})
    wrapper = _StructuredOutputWithFallback(_Schema, fake)

    assert wrapper.invoke([("system", "s"), ("human", "h")]).ok is True
    assert [len(function_calling.calls), len(json_mode.calls)] == [1, 1]
    # JSON 模式必须带上显式 schema 指令。
    assert json_mode.calls[0][-1][0] == "human"
    assert "JSON Schema" in json_mode.calls[0][-1][1]

    # 成功的方法会被记住，下次不再先调用失败的方法。
    assert wrapper.invoke([("system", "s"), ("human", "h")]).ok is True
    assert [len(function_calling.calls), len(json_mode.calls)] == [1, 2]


def test_format_error_falls_back_but_auth_error_does_not(monkeypatch):
    monkeypatch.setenv("OPENAI_STRUCTURED_METHOD", "function_calling")
    function_calling = _Runnable(error=ValueError("unsupported tool schema"))
    json_mode = _Runnable(parsed=_Schema(ok=True))
    fake = _FakeLLM({"function_calling": function_calling, "json_mode": json_mode})
    wrapper = _StructuredOutputWithFallback(_Schema, fake)
    assert wrapper.invoke([("human", "h")]).ok is True

    auth_error = PermissionError("401 authentication failed")
    fake_auth = _FakeLLM({
        "function_calling": _Runnable(error=auth_error),
        "json_mode": json_mode,
    })
    wrapper_auth = _StructuredOutputWithFallback(_Schema, fake_auth)
    with pytest.raises(PermissionError):
        wrapper_auth.invoke([("human", "h")])
