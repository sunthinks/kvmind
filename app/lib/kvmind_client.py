"""
KVMind AI Client v3 — Stateless Prompt Assembler

Stateless: does NOT manage conversation history.
History is owned by the caller (Runner).
This client's job: assemble prompts, inject memory, call router.

Two methods:
  decide(history, tools, lang) → RouteResult   (auto mode — with tools)
  analyse(message, screenshot, lang) → str      (suggest/ask — text only)

Stage timeouts (task-driven, not model-driven):
  decide = 30s (quick: look at screen + decide next action)
  analyse = 60s (deeper: analyze screen + compose answer)
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from .ai_intents import INTENT_DECIDE, INTENT_ANALYSE, INTENT_OCR, AnalysisResponse
from .model_router import RouteResult

if TYPE_CHECKING:
    from .config import AIConfig
    from .model_router import ModelRouter
    from .memory_store import MemoryStore

log = logging.getLogger(__name__)

_LANG_MAP = {"zh": "Chinese (简体中文)", "ja": "Japanese (日本語)", "en": "English"}

# Stage timeouts — task-driven, model-agnostic
STAGE_TIMEOUT = {
    "decide": 30,
    "analyse": 60,
    "ocr": 45,
}


class KVMindClient:
    """Stateless AI client. History is a parameter, not internal state."""

    def __init__(
        self,
        cfg: "AIConfig",
        router: "ModelRouter",
        memory: Optional["MemoryStore"] = None,
    ) -> None:
        self._cfg = cfg
        self._router = router
        self._memory = memory

    async def decide(
        self,
        history: list[dict],
        tools: list[dict],
        lang: str = "zh",
        cloud_prompt: str | None = None,
    ) -> RouteResult:
        """Send history + tools to AI, get structured response with meta.

        Stateless: caller manages history.
        If cloud_prompt is provided (from kdcms), uses it instead of local prompt.
        Returns RouteResult (response + meta for logging).
        """
        if cloud_prompt:
            system_prompt = await self._finalize_prompt(cloud_prompt, INTENT_DECIDE, lang)
        else:
            system_prompt = await self._build_prompt(INTENT_DECIDE, lang)

        result = await self._router.send(
            system_prompt=system_prompt,
            messages=history,
            max_tokens=self._cfg.max_tokens,
            tools=tools,
            timeout=STAGE_TIMEOUT["decide"],
        )

        log.info(
            "[KVMind] decide: text=%d, actions=%d, via=%s/%s",
            len(result.response.text), len(result.response.tool_calls),
            result.meta.provider_name, result.meta.model,
        )
        return result

    async def analyse(
        self,
        message: str,
        screenshot_b64: str | None = None,
        lang: str = "zh",
        cloud_prompt: str | None = None,
    ) -> str:
        """Single-turn analysis/Q&A. Returns plain text."""
        if cloud_prompt:
            system_prompt = await self._finalize_prompt(cloud_prompt, INTENT_ANALYSE, lang)
        else:
            system_prompt = await self._build_prompt(INTENT_ANALYSE, lang)

        content: list[dict] = [{"type": "text", "text": message}]
        if screenshot_b64:
            content.append({"type": "image_b64", "data": screenshot_b64})

        result = await self._router.send(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": content}],
            max_tokens=self._cfg.max_tokens,
            timeout=STAGE_TIMEOUT["analyse"],
        )

        text = result.response.text

        # Extract memory tags from response
        if self._memory and INTENT_ANALYSE.parser:
            parsed = INTENT_ANALYSE.parser(text)
            if isinstance(parsed, AnalysisResponse):
                await self._process_memory_ops(parsed.memory_ops)
                text = parsed.text

        return text

    async def ocr(
        self,
        screenshot_b64: str,
        lang: str = "en",
    ) -> str:
        """Extract all visible text from a screenshot.

        Stateless, no memory, no tools.
        """
        system_prompt = await self._build_prompt(INTENT_OCR, lang)
        content: list[dict] = [
            {"type": "text", "text": "Extract all visible text from this screenshot."},
            {"type": "image_b64", "data": screenshot_b64},
        ]
        result = await self._router.send(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": content}],
            max_tokens=self._cfg.max_tokens,
            timeout=STAGE_TIMEOUT["ocr"],
        )
        return result.response.text.strip()

    async def _finalize_prompt(self, cloud_prompt: str, intent, lang: str) -> str:
        """Finalize a cloud-provided prompt: append language + memory."""
        prompt = cloud_prompt
        lang_name = _LANG_MAP.get(lang, "English")
        prompt += f"\n\nIMPORTANT: You MUST respond in {lang_name}. All observations, explanations, and status reports must be in {lang_name}."
        if self._memory and intent.memory_instruction:
            prompt += intent.memory_instruction
            memories = await self._memory.recall(limit=10)
            memory_text = self._memory.format_for_prompt(memories)
            if memory_text:
                prompt += f"\n\nCurrent memories:\n{memory_text}"
        return prompt

    async def _build_prompt(self, intent, lang: str) -> str:
        """Assemble system prompt: base + language + memory."""
        prompt = intent.get_system_prompt()

        lang_name = _LANG_MAP.get(lang, "English")
        prompt += f"\n\nIMPORTANT: You MUST respond in {lang_name}. All observations, explanations, and status reports must be in {lang_name}."

        if self._memory and intent.memory_instruction:
            prompt += intent.memory_instruction
            memories = await self._memory.recall(limit=10)
            memory_text = self._memory.format_for_prompt(memories)
            if memory_text:
                prompt += f"\n\nCurrent memories:\n{memory_text}"

        return prompt

    async def _process_memory_ops(self, memory_ops: list[dict]) -> None:
        if not self._memory:
            return
        for op in memory_ops:
            category = op.get("category", "knowledge")
            content = op.get("content", "")
            if content:
                await self._memory.save(category, content, source="ai_extracted")
