"""Tests for model_router.py — fallback logic and degraded responses."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_provider import ProviderResponse, is_tool_noise
from lib.model_router import ModelRouter, RouteResult, RouteMeta


def run(coro):
    """Helper to run async coroutines."""
    return asyncio.get_event_loop().run_until_complete(coro)


def make_mock_provider(
    name: str = "test",
    default_model: str = "test-model",
    response: ProviderResponse | None = None,
    error: Exception | None = None,
) -> MagicMock:
    """Create a mock AIProvider."""
    provider = MagicMock()
    provider.default_model = default_model
    if error:
        provider.send = AsyncMock(side_effect=error)
    elif response:
        provider.send = AsyncMock(return_value=response)
    else:
        provider.send = AsyncMock(return_value=ProviderResponse(text="OK", tool_calls=[], stop_reason="end_turn"))
    return provider


class TestFallbackLogic:
    def test_first_provider_succeeds(self):
        p1 = make_mock_provider("primary", "model-a")
        p2 = make_mock_provider("fallback", "model-b")
        router = ModelRouter(providers={"primary": p1, "fallback": p2})

        result = run(router.send("system", [{"role": "user", "content": "hello"}]))

        assert isinstance(result, RouteResult)
        assert result.meta.provider_name == "primary"
        assert result.meta.model == "model-a"
        assert result.meta.fallback_used is False
        assert result.meta.attempts == 1
        assert result.response.text == "OK"

        p1.send.assert_awaited_once()
        p2.send.assert_not_awaited()

    def test_fallback_on_primary_failure(self):
        p1 = make_mock_provider("primary", error=RuntimeError("timeout"))
        p2 = make_mock_provider("fallback", "model-b",
                                response=ProviderResponse(text="Fallback OK", tool_calls=[], stop_reason="end_turn"))
        router = ModelRouter(providers={"primary": p1, "fallback": p2})

        result = run(router.send("system", [{"role": "user", "content": "hello"}]))

        assert result.meta.provider_name == "fallback"
        assert result.meta.fallback_used is True
        assert result.meta.attempts == 2
        assert result.response.text == "Fallback OK"

    def test_semantic_invalid_triggers_fallback(self):
        # Empty response when tools are provided is semantically invalid
        empty_resp = ProviderResponse(text="", tool_calls=[], stop_reason="end_turn")
        p1 = make_mock_provider("primary", response=empty_resp)
        good_resp = ProviderResponse(text="Used tools", tool_calls=[{"id": "1", "name": "click", "args": {}}], stop_reason="tool_use")
        p2 = make_mock_provider("fallback", response=good_resp)
        router = ModelRouter(providers={"primary": p1, "fallback": p2})

        tools = [{"type": "function", "function": {"name": "click"}}]
        result = run(router.send("system", [{"role": "user", "content": "do something"}], tools=tools))

        assert result.meta.provider_name == "fallback"
        assert result.meta.fallback_used is True

    def test_text_only_response_with_tools_is_valid(self):
        # Text response without tool calls is valid even when tools are available
        text_resp = ProviderResponse(text="I'll just answer.", tool_calls=[], stop_reason="end_turn")
        p1 = make_mock_provider("primary", response=text_resp)
        router = ModelRouter(providers={"primary": p1})

        tools = [{"type": "function", "function": {"name": "click"}}]
        result = run(router.send("system", [{"role": "user", "content": "what model?"}], tools=tools))

        assert result.meta.provider_name == "primary"
        assert result.response.text == "I'll just answer."

    def test_single_embedded_tool_json_triggers_no_tool_support(self):
        # Local models may emit a single shorthand JSON tool as text.
        # It must be rejected, not displayed or executed.
        json_resp = ProviderResponse(text='{"text":"clear"}', tool_calls=[], stop_reason="end_turn")
        p1 = make_mock_provider("primary", response=json_resp)
        router = ModelRouter(providers={"primary": p1})

        tools = [{"type": "function", "function": {"name": "type_text"}}]
        result = run(router.send("system", [{"role": "user", "content": "clear terminal"}], tools=tools))

        assert result.meta.provider_name == "none"
        assert result.response.stop_reason == "no_tool_support"
        assert result.response.text == ""

    def test_nested_embedded_tool_json_is_detected(self):
        resp = ProviderResponse(
            text='{"name":"type_text","args":{"text":"clear"}}',
            tool_calls=[],
            stop_reason="end_turn",
        )

        assert resp.has_embedded_tool_json({"type_text"}) is True
        assert is_tool_noise(resp.text) is True

    def test_prefixed_nested_embedded_tool_json_is_detected(self):
        resp = ProviderResponse(
            text='Action: {"name":"type_text","args":{"text":"clear"}}',
            tool_calls=[],
            stop_reason="end_turn",
        )

        assert resp.has_embedded_tool_json({"type_text"}) is True
        assert is_tool_noise(resp.text) is True


class TestDegradedResponse:
    def test_all_providers_fail_returns_degraded(self):
        p1 = make_mock_provider("primary", error=RuntimeError("fail1"))
        p2 = make_mock_provider("fallback", error=RuntimeError("fail2"))
        router = ModelRouter(providers={"primary": p1, "fallback": p2})

        result = run(router.send("system", [{"role": "user", "content": "hello"}]))

        # Should NOT raise — returns degraded response
        assert isinstance(result, RouteResult)
        assert result.meta.provider_name == "none"
        assert result.meta.model == "none"
        assert result.meta.fallback_used is True
        assert result.meta.attempts == 2
        assert result.response.stop_reason == "error"
        assert len(result.response.text) > 0  # Should have a user-facing message

    def test_single_provider_fails_returns_degraded(self):
        p1 = make_mock_provider("only", error=ConnectionError("offline"))
        router = ModelRouter(providers={"only": p1})

        result = run(router.send("system", [{"role": "user", "content": "hi"}]))

        assert result.meta.provider_name == "none"
        assert result.response.stop_reason == "error"

    def test_never_raises(self):
        p1 = make_mock_provider("a", error=Exception("boom"))
        p2 = make_mock_provider("b", error=TypeError("type error"))
        p3 = make_mock_provider("c", error=ValueError("value error"))
        router = ModelRouter(providers={"a": p1, "b": p2, "c": p3})

        # This must NOT raise
        result = run(router.send("system", [{"role": "user", "content": "test"}]))

        assert result is not None
        assert result.meta.provider_name == "none"


class TestTimeout:
    def test_default_timeout_passed_to_provider(self):
        p1 = make_mock_provider("primary")
        router = ModelRouter(providers={"primary": p1}, default_timeout=30)

        run(router.send("system", [{"role": "user", "content": "hi"}]))

        call_kwargs = p1.send.call_args.kwargs
        assert call_kwargs["timeout"] == 30

    def test_per_call_timeout_override(self):
        p1 = make_mock_provider("primary")
        router = ModelRouter(providers={"primary": p1}, default_timeout=30)

        run(router.send("system", [{"role": "user", "content": "hi"}], timeout=60))

        call_kwargs = p1.send.call_args.kwargs
        assert call_kwargs["timeout"] == 60


class TestRouteMeta:
    def test_route_meta_fields(self):
        meta = RouteMeta(provider_name="gemini", model="gemini-2.5-flash", attempts=1, fallback_used=False)

        assert meta.provider_name == "gemini"
        assert meta.model == "gemini-2.5-flash"
        assert meta.attempts == 1
        assert meta.fallback_used is False
