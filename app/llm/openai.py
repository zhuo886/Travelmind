"""OpenAI structured-output client factory."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.env import load_local_env
from app.core.http import choose_http_proxy


logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"
DEFAULT_REASONING_EFFORT = "none"

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def resolve_openai_model(model: str | None = None) -> str:
    return (model or os.getenv("OPENAI_MODEL") or os.getenv("AI_MODEL") or DEFAULT_OPENAI_MODEL).strip()


def resolve_openai_base_url() -> str | None:
    """Resolve an optional OpenAI-compatible proxy endpoint."""
    value = (os.getenv("OPENAI_BASE_URL") or os.getenv("AI_BASE_URL") or "").strip()
    return value.rstrip("/") or None


def use_openai_responses_api() -> bool:
    value = (os.getenv("OPENAI_USE_RESPONSES_API") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def resolve_reasoning_effort() -> str:
    effort = os.getenv(
        "TRAVELMIND_OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT
    ).strip().lower()
    supported = {"none", "low", "medium", "high", "xhigh", "max"}
    if effort not in supported:
        raise ValueError(
            f"未知的 OpenAI reasoning effort：{effort}，支持：{', '.join(sorted(supported))}"
        )
    return effort


def resolve_max_tokens() -> int | None:
    """可选的输出上限。部分中转在流式生成时不触发读超时，
    一个跑飞的响应可以占掉 5-10 分钟，用 max_tokens 兜住上限。"""
    raw = (os.getenv("OPENAI_MAX_TOKENS") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def resolve_extra_body(thinking: bool | None = None) -> dict[str, Any]:
    """控制中转的隐藏思考链。

    ``thinking`` 显式传入时优先（True = 走厂商默认的开启状态，False = 显式关闭）；
    未传入时看 ``OPENAI_THINKING``。智谱 GLM 默认返回 ``reasoning_content``，
    一个 planner 请求光思考就能跑 300-800 秒（日志实测）。
    """
    if thinking is True:
        return {}
    if thinking is False:
        return {"thinking": {"type": "disabled"}}
    mode = (os.getenv("OPENAI_THINKING") or "").strip().lower()
    if mode in {"disabled", "off", "0", "false"}:
        return {"thinking": {"type": "disabled"}}
    if mode in {"enabled", "on", "1", "true"}:
        return {"thinking": {"type": "enabled"}}
    return {}


def build_chat_openai(
    *, model: str | None = None, temperature: float = 0, thinking: bool | None = None
) -> Any:
    """Create an OpenAI client using the Responses API."""
    load_local_env()
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY。请在 .env.local 中配置后重试。")
    try:
        import httpx
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 httpx 或 langchain-openai。请先安装依赖。") from exc

    proxy = choose_http_proxy()
    kwargs: dict[str, Any] = {}
    max_tokens = resolve_max_tokens()
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra_body = resolve_extra_body(thinking)
    if extra_body:
        kwargs["extra_body"] = extra_body
    return ChatOpenAI(
        model=resolve_openai_model(model),
        api_key=api_key,
        base_url=resolve_openai_base_url(),
        temperature=temperature,
        reasoning_effort=resolve_reasoning_effort(),
        use_responses_api=use_openai_responses_api(),
        timeout=120,
        max_retries=2,
        http_client=httpx.Client(proxy=proxy, trust_env=False),
        http_async_client=httpx.AsyncClient(proxy=proxy, trust_env=False),
        http_socket_options=(),
        **kwargs,
    )


def resolve_structured_method() -> str:
    """Resolve the structured-output method for OpenAI-compatible endpoints.

    Strict ``json_schema`` requires the endpoint to emit raw JSON while
    streaming; proxies such as Zhipu return plain text instead, which makes the
    OpenAI SDK fail with "expected value at line 1 column 1". Set
    ``OPENAI_STRUCTURED_METHOD=function_calling`` (or ``json_mode``) to degrade.
    """
    value = (os.getenv("OPENAI_STRUCTURED_METHOD") or "json_schema").strip().lower()
    if value not in {"json_schema", "function_calling", "json_mode"}:
        return "json_schema"
    return value


def _structured_fallback_methods() -> list[str]:
    """Primary structured method followed by progressively simpler fallbacks."""
    primary = resolve_structured_method()
    if primary == "json_schema":
        return ["json_schema", "function_calling", "json_mode"]
    if primary == "function_calling":
        return ["function_calling", "json_mode"]
    return ["json_mode", "function_calling"]


def _can_fallback_on(exc: Exception) -> bool:
    """Only switch methods for format/capability errors, never for auth/network issues."""
    name = type(exc).__name__.lower()
    if any(token in name for token in ("timeout", "connection", "ratelimit")):
        return False
    status = getattr(exc, "status_code", None)
    if status == 429 or (isinstance(status, int) and status >= 500):
        return False
    text = str(exc).lower()
    return any(token in text for token in (
        "json", "schema", "tool", "function", "parse", "structured",
        "response_format", "400", "bad request",
    ))


def _json_mode_messages(schema: type[BaseModel], messages: list[Any]) -> list[Any]:
    """JSON mode needs an explicit schema instruction in the prompt."""
    schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return [*messages, (
        "human",
        "请只返回一个合法 JSON 对象，不要输出 markdown、代码块或额外解释；"
        f"字段与类型必须严格符合以下 JSON Schema：\n{schema_text}",
    )]


class _StructuredOutputWithFallback:
    """Try the configured structured method, then degrade to another method.

    Zhipu-compatible endpoints occasionally accept a function-calling request
    but return no tool call, which LangChain surfaces as ``parsed=None``.
    Retrying the same method wastes 1-2 minutes; switching to JSON mode keeps
    the planning run alive and records which method actually worked.
    """

    def __init__(self, schema: type[SchemaT], llm: Any):
        self.schema = schema
        self.model_name = str(
            getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"
        )
        self.model = self.model_name
        self._chains: list[tuple[str, Any]] = []
        for method in _structured_fallback_methods():
            kwargs: dict[str, Any] = {"method": method, "include_raw": True}
            if method == "json_schema":
                kwargs["strict"] = True
            try:
                runnable = llm.with_structured_output(schema, **kwargs)
            except Exception as exc:  # noqa: BLE001 - a method may be unsupported up front
                logger.warning(
                    "[structured] 无法初始化 method=%s（%s），跳过", method, type(exc).__name__,
                )
                continue
            self._chains.append((method, runnable))
        if not self._chains:
            raise RuntimeError("没有可用的结构化输出方法，请检查 OPENAI_STRUCTURED_METHOD 配置")

    def _mark_preferred(self, index: int) -> None:
        if index > 0:
            method = self._chains[index][0]
            self._chains.insert(0, self._chains.pop(index))
            logger.warning("[structured] 已切换到可用方法 method=%s", method)

    def invoke(self, messages: list[Any], **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for index, (method, runnable) in enumerate(list(self._chains)):
            call_messages = _json_mode_messages(self.schema, messages) if method == "json_mode" else messages
            try:
                output = runnable.invoke(call_messages, **kwargs)
            except Exception as exc:  # noqa: BLE001 - try the next format method
                if not _can_fallback_on(exc):
                    raise
                logger.warning(
                    "[structured] method=%s 调用失败（%s），尝试下一方法",
                    method, type(exc).__name__,
                )
                last_error = exc
                continue

            parsed = output.get("parsed") if isinstance(output, dict) else output
            if parsed is not None:
                self._mark_preferred(index)
                return parsed

            raw = output.get("raw") if isinstance(output, dict) else None
            parsing_error = output.get("parsing_error") if isinstance(output, dict) else None
            finish_reason = None
            if raw is not None:
                finish_reason = (getattr(raw, "response_metadata", {}) or {}).get("finish_reason")
            logger.warning(
                "[structured] method=%s 返回 None parsing_error=%s finish_reason=%s "
                "content_chars=%d tool_calls=%d，尝试下一方法",
                method,
                type(parsing_error).__name__ if parsing_error else "none",
                finish_reason,
                len(str(getattr(raw, "content", "") or "")),
                len(getattr(raw, "tool_calls", None) or []),
            )

        if last_error is not None:
            raise last_error
        return None

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.invoke, messages, **kwargs)


def build_structured_openai(
    schema: type[SchemaT],
    *,
    model: str | None = None,
    temperature: float = 0,
    thinking: bool | None = None,
) -> Any:
    """Create an OpenAI client bound to a Pydantic schema with format fallback."""
    llm = build_chat_openai(model=model, temperature=temperature, thinking=thinking)
    return _StructuredOutputWithFallback(schema, llm)
