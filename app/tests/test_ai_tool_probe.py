"""Pin the supports_tools probe behaviour.

Earlier the probe sent a casual prompt with default tool_choice="auto".
qwen2.5/qwen3 7-14B class models on Ollama are technically function-call
trained but, given the loose prompt, often answered in prose and never
emitted tool_calls — flipping supports_tools=False and downgrading
auto→suggest in chat. The probe now forces tool_choice="required" and
falls back to "no tool_choice" only when the runtime rejects the param
(older Ollama / some self-hosted gateways return 400/422).

These tests pin both paths so the regression doesn't sneak back in.
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.handlers.ai_config import _test_tool_calling


def _mock_session(responses):
    """Build a fake aiohttp ClientSession.post() that returns scripted responses.

    `responses` is a list of (status, json_body) tuples — one per expected
    POST. The last response is reused if the probe makes more calls than
    scripted (so a misbehaving probe surfaces as a wrong assertion, not a
    StopIteration).
    """
    calls = []

    @asynccontextmanager
    async def _post(url, json=None, headers=None, timeout=None, ssl=None):
        idx = len(calls)
        calls.append({"json": json, "url": url})
        status, body = responses[min(idx, len(responses) - 1)]
        resp = MagicMock()
        resp.status = status

        async def _json():
            return body

        resp.json = _json
        yield resp

    session = MagicMock()
    session.post = _post
    return session, calls


@pytest.mark.asyncio
async def test_required_succeeds_with_tool_calls():
    """Happy path: runtime accepts tool_choice=required, model emits tool_calls."""
    session, calls = _mock_session([
        (200, {"choices": [{"message": {"tool_calls": [{"id": "1", "type": "function"}]}}]}),
    ])

    result = await _test_tool_calling(session, "https://example/v1/chat/completions", {}, "qwen2.5:7b")

    assert result is True
    assert len(calls) == 1
    assert calls[0]["json"]["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_required_succeeds_but_no_tool_calls():
    """Edge: runtime accepts the param but model still answers in prose.

    A genuinely incapable model still resolves to False — we don't paper
    over real failure with the fallback path.
    """
    session, calls = _mock_session([
        (200, {"choices": [{"message": {"content": "Sure!"}}]}),
    ])

    result = await _test_tool_calling(session, "https://example/v1/chat/completions", {}, "ancient-base-model")

    assert result is False
    assert len(calls) == 1  # no fallback when first attempt was a clean 200


@pytest.mark.asyncio
async def test_required_rejected_then_fallback_succeeds():
    """Compat: older Ollama 400s on tool_choice=required, fallback wins."""
    session, calls = _mock_session([
        (400, None),
        (200, {"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]}),
    ])

    result = await _test_tool_calling(session, "http://192.168.1.5:11434/v1/chat/completions", {}, "qwen2.5:7b")

    assert result is True
    assert len(calls) == 2
    assert calls[0]["json"]["tool_choice"] == "required"
    assert "tool_choice" not in calls[1]["json"]


@pytest.mark.asyncio
async def test_required_rejected_and_fallback_fails():
    """Both probes fail → False (don't accidentally call it capable)."""
    session, calls = _mock_session([
        (422, None),
        (200, {"choices": [{"message": {"content": "no tools here"}}]}),
    ])

    result = await _test_tool_calling(session, "http://h/v1/chat/completions", {}, "weak-model")

    assert result is False
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_non_400_error_short_circuits():
    """5xx / 401 / 404 don't trigger the compat fallback (not a param issue)."""
    session, calls = _mock_session([
        (500, None),
        # Second entry would be reused if probe fell through — assertion below proves it didn't.
        (200, {"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]}),
    ])

    result = await _test_tool_calling(session, "http://h/v1/chat/completions", {}, "m")

    assert result is False
    assert len(calls) == 1
