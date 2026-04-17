"""Tests for intent_gate.py — language-agnostic three-level intent classification."""
import json
import sys
import os
import pytest
from unittest.mock import AsyncMock
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.innerclaw.intent_gate import (
    classify_intent, CONFIDENCE_THRESHOLD,
    INTENT_CHAT, INTENT_INVESTIGATE, INTENT_EXECUTE, _TOOL_INTENTS,
)


@dataclass
class FakeResponse:
    text: str
    tool_calls: list = None
    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []

@dataclass
class FakeMeta:
    provider_name: str = "test"
    model: str = "test"
    attempts: int = 1
    fallback_used: bool = False

@dataclass
class FakeResult:
    response: FakeResponse
    meta: FakeMeta = None
    def __post_init__(self):
        if self.meta is None:
            self.meta = FakeMeta()


def make_router(intent: str, confidence: float) -> AsyncMock:
    router = AsyncMock()
    router.send = AsyncMock(return_value=FakeResult(FakeResponse(
        text=json.dumps({"intent": intent, "confidence": confidence})
    )))
    return router


# ── Three-Level Classification ─────────────────────────────────────────

class TestThreeLevels:
    def test_intent_constants(self):
        assert INTENT_CHAT == "CHAT"
        assert INTENT_INVESTIGATE == "INVESTIGATE"
        assert INTENT_EXECUTE == "EXECUTE"

    def test_tool_intents_include_investigate_and_execute(self):
        assert INTENT_INVESTIGATE in _TOOL_INTENTS
        assert INTENT_EXECUTE in _TOOL_INTENTS
        assert INTENT_CHAT not in _TOOL_INTENTS

    @pytest.mark.asyncio
    async def test_chat_classification(self):
        router = make_router("CHAT", 0.95)
        intent, conf = await classify_intent(router, "你好")
        assert intent == "CHAT"

    @pytest.mark.asyncio
    async def test_investigate_classification(self):
        router = make_router("INVESTIGATE", 0.90)
        intent, conf = await classify_intent(router, "有可以清空的文件吗？")
        assert intent == "INVESTIGATE"
        assert intent in _TOOL_INTENTS  # tools should be kept

    @pytest.mark.asyncio
    async def test_execute_classification(self):
        router = make_router("EXECUTE", 0.95)
        intent, conf = await classify_intent(router, "清空所有日志")
        assert intent == "EXECUTE"
        assert intent in _TOOL_INTENTS  # tools should be kept


# ── Fail-Safe Behavior ────────────────────────────────────────────────

class TestFailSafe:
    @pytest.mark.asyncio
    async def test_exception_returns_investigate(self):
        """Fail-safe is INVESTIGATE (keep tools), not CHAT."""
        router = AsyncMock()
        router.send = AsyncMock(side_effect=Exception("network error"))
        intent, conf = await classify_intent(router, "anything")
        assert intent == "INVESTIGATE"
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_invalid_json_returns_investigate(self):
        router = AsyncMock()
        router.send = AsyncMock(return_value=FakeResult(FakeResponse(text='not json')))
        intent, conf = await classify_intent(router, "anything")
        assert intent == "INVESTIGATE"

    @pytest.mark.asyncio
    async def test_truncated_json_returns_investigate(self):
        """The actual bug from production: AI returned '{"intent":' (truncated)."""
        router = AsyncMock()
        router.send = AsyncMock(return_value=FakeResult(FakeResponse(text='{"intent":')))
        intent, conf = await classify_intent(router, "有可以清空的文件吗？")
        assert intent == "INVESTIGATE"  # fail-safe keeps tools

    @pytest.mark.asyncio
    async def test_unknown_intent_returns_investigate(self):
        router = AsyncMock()
        router.send = AsyncMock(return_value=FakeResult(FakeResponse(
            text='{"intent": "UNKNOWN", "confidence": 0.99}'
        )))
        intent, conf = await classify_intent(router, "anything")
        assert intent == "INVESTIGATE"

    @pytest.mark.asyncio
    async def test_timeout_returns_investigate(self):
        import asyncio
        router = AsyncMock()
        router.send = AsyncMock(side_effect=asyncio.TimeoutError())
        intent, conf = await classify_intent(router, "anything")
        assert intent == "INVESTIGATE"


# ── JSON Parsing ───────────────────────────────────────────────────────

class TestJsonParsing:
    @pytest.mark.asyncio
    async def test_clean_json(self):
        router = make_router("EXECUTE", 0.95)
        intent, conf = await classify_intent(router, "delete files")
        assert intent == "EXECUTE"
        assert conf == 0.95

    @pytest.mark.asyncio
    async def test_json_in_markdown_fence(self):
        router = AsyncMock()
        router.send = AsyncMock(return_value=FakeResult(FakeResponse(
            text='```json\n{"intent": "CHAT", "confidence": 0.9}\n```'
        )))
        intent, conf = await classify_intent(router, "hello")
        assert intent == "CHAT"

    @pytest.mark.asyncio
    async def test_json_with_extra_text(self):
        router = AsyncMock()
        router.send = AsyncMock(return_value=FakeResult(FakeResponse(
            text='Here: {"intent": "INVESTIGATE", "confidence": 0.8}'
        )))
        intent, conf = await classify_intent(router, "check disk")
        assert intent == "INVESTIGATE"


# ── Multi-Language (intent processed correctly) ───────────────────────

class TestMultiLanguage:
    @pytest.mark.asyncio
    async def test_chinese_investigate(self):
        """'有可以清空的文件吗？' should be INVESTIGATE — needs system access to answer."""
        router = make_router("INVESTIGATE", 0.92)
        intent, _ = await classify_intent(router, "有可以清空的文件吗？")
        assert intent == "INVESTIGATE"
        assert intent in _TOOL_INTENTS

    @pytest.mark.asyncio
    async def test_chinese_execute(self):
        router = make_router("EXECUTE", 0.95)
        intent, _ = await classify_intent(router, "清空所有日志")
        assert intent == "EXECUTE"

    @pytest.mark.asyncio
    async def test_chinese_chat(self):
        router = make_router("CHAT", 0.90)
        intent, _ = await classify_intent(router, "你是什么模型？")
        assert intent == "CHAT"

    @pytest.mark.asyncio
    async def test_japanese_investigate(self):
        router = make_router("INVESTIGATE", 0.88)
        intent, _ = await classify_intent(router, "ファイルを削除できますか？")
        assert intent == "INVESTIGATE"

    @pytest.mark.asyncio
    async def test_korean_investigate(self):
        router = make_router("INVESTIGATE", 0.90)
        intent, _ = await classify_intent(router, "삭제할 수 있는 파일이 있나요?")
        assert intent == "INVESTIGATE"

    @pytest.mark.asyncio
    async def test_english_investigate(self):
        router = make_router("INVESTIGATE", 0.85)
        intent, _ = await classify_intent(router, "What files can I safely delete?")
        assert intent == "INVESTIGATE"

    @pytest.mark.asyncio
    async def test_english_execute(self):
        router = make_router("EXECUTE", 0.97)
        intent, _ = await classify_intent(router, "Delete all temp files")
        assert intent == "EXECUTE"

    @pytest.mark.asyncio
    async def test_english_chat(self):
        router = make_router("CHAT", 0.93)
        intent, _ = await classify_intent(router, "How does a KVM switch work?")
        assert intent == "CHAT"


# ── Router Call Verification ──────────────────────────────────────────

class TestRouterCall:
    @pytest.mark.asyncio
    async def test_sends_message(self):
        router = make_router("CHAT", 0.9)
        await classify_intent(router, "test message")
        router.send.assert_called_once()
        call_kwargs = router.send.call_args[1]
        assert call_kwargs["max_tokens"] == 80
        assert call_kwargs["timeout"] == 8
        assert call_kwargs["messages"][0]["content"] == "test message"

    @pytest.mark.asyncio
    async def test_no_tools_passed(self):
        router = make_router("EXECUTE", 0.9)
        await classify_intent(router, "do something")
        call_kwargs = router.send.call_args[1]
        assert "tools" not in call_kwargs or call_kwargs.get("tools") is None
