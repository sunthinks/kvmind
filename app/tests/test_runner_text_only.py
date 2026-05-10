"""Runner text-only final handling."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ai_provider import ProviderResponse
from lib.innerclaw.budget import Budget
from lib.innerclaw.runner import Runner
from lib.model_router import RouteMeta, RouteResult


class _FakeKVM:
    async def snapshot_b64(self) -> str:
        return "fake-screenshot"


class _TextOnlyAI:
    def __init__(self, supports_tools: bool) -> None:
        self._cfg = SimpleNamespace(supports_tools=supports_tools)
        self._router = object()
        self.calls = 0

    async def decide(self, history, tools, lang="zh", **kwargs) -> RouteResult:
        self.calls += 1
        return RouteResult(
            response=ProviderResponse(
                text=f"final answer {self.calls}",
                tool_calls=[],
                stop_reason="end_turn",
            ),
            meta=RouteMeta(
                provider_name="gemini",
                model="gemini-2.5-flash",
                attempts=1,
                fallback_used=False,
            ),
        )


async def _collect_agentic_events(supports_tools: bool) -> list[dict]:
    ai = _TextOnlyAI(supports_tools=supports_tools)
    runner = Runner(_FakeKVM(), ai, audit=object(), mode="auto", lang="zh")
    runner._context = []
    budget = Budget(max_ai_calls=5)
    budget.start()

    events = []
    async for event in runner._agentic_loop("检查磁盘空间", budget):
        events.append(event.as_dict())
    assert ai.calls == 2
    return events


@pytest.mark.asyncio
async def test_text_only_final_does_not_warn_when_model_supports_tools():
    events = await _collect_agentic_events(supports_tools=True)

    assert not any(
        event.get("code") == "auto_text_only_no_tool_calls"
        for event in events
    )
    assert events[-2]["event"] == "ai_text"
    assert events[-1]["event"] == "task_done"


@pytest.mark.asyncio
async def test_text_only_final_warns_when_model_marked_tool_incapable():
    events = await _collect_agentic_events(supports_tools=False)

    notices = [
        event for event in events
        if event.get("code") == "auto_text_only_no_tool_calls"
    ]
    assert len(notices) == 1
    assert notices[0]["severity"] == "warn"
