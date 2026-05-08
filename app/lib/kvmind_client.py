"""
KVMind AI Client v4 — Structured Failure Contract

Stateless: does NOT manage conversation history.
History is owned by the caller (Runner).
This client's job: assemble prompts, inject memory, call router.

Three methods:
  decide(history, tools, lang)    → RouteResult  (auto — Runner inspects meta)
  analyse(message, screenshot, lang) → str       (raises AIError on failure)
  ocr(screenshot, lang)           → str          (raises AIError on failure)

Failure contract:
  decide() returns RouteResult — caller must branch on .ok / meta.error_code.
  analyse()/ocr() raise AIError subclass on router failure. Callers at the
  handler layer catch AIError and map code → localized message.

Stage timeouts (task-driven, not model-driven):
  decide  = 30s (quick: look at screen + decide next action)
  analyse = 60s (deeper: analyze screen + compose answer)
  ocr     = 90s (heaviest: full-frame text extraction)
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from .ai_intents import INTENT_DECIDE, INTENT_ANALYSE, INTENT_OCR, AnalysisResponse
from .model_router import (
    RouteResult,
    ERROR_NO_PROVIDERS,
    ERROR_TIMEOUT,
    ERROR_CONNECT,
    ERROR_EMPTY,
    ERROR_NO_TOOL_SUPPORT,
    ERROR_FAILED,
)

if TYPE_CHECKING:
    from .config import AIConfig
    from .model_router import ModelRouter
    from .memory_store import MemoryStore

log = logging.getLogger(__name__)

_LANG_MAP = {"zh": "Chinese (简体中文)", "ja": "Japanese (日本語)", "en": "English"}


# ── Typed exceptions (code-carrying, no user-facing strings) ─────────────────

class AIError(Exception):
    """Base exception for AI call failures. Carries a canonical error code.

    Handlers map `.code` to a localized user message using the request's lang.
    Never construct with a pre-localized message — keep it code-only so the
    i18n boundary stays at the handler layer.
    """

    code: str = ERROR_FAILED

    def __init__(self, code: str | None = None, detail: str = "") -> None:
        if code:
            self.code = code
        self.detail = detail
        super().__init__(f"{self.code}" + (f": {detail}" if detail else ""))


class AINoProvidersError(AIError):
    code = ERROR_NO_PROVIDERS


class AITimeoutError(AIError):
    code = ERROR_TIMEOUT


class AIConnectError(AIError):
    code = ERROR_CONNECT


class AIEmptyError(AIError):
    code = ERROR_EMPTY


class AINoToolSupportError(AIError):
    code = ERROR_NO_TOOL_SUPPORT


class AIFailedError(AIError):
    code = ERROR_FAILED


_CODE_TO_EXC: dict[str, type[AIError]] = {
    ERROR_NO_PROVIDERS: AINoProvidersError,
    ERROR_TIMEOUT: AITimeoutError,
    ERROR_CONNECT: AIConnectError,
    ERROR_EMPTY: AIEmptyError,
    ERROR_NO_TOOL_SUPPORT: AINoToolSupportError,
    ERROR_FAILED: AIFailedError,
}


def _raise_from_route(result: RouteResult) -> None:
    """If result carries a failure code, raise the matching AIError."""
    code = result.meta.error_code
    if code is None:
        return
    exc_cls = _CODE_TO_EXC.get(code, AIFailedError)
    raise exc_cls(code=code)


# ── AI error localization (single source of truth, shared by runner + handlers) ──

_AI_ERROR_MESSAGES: dict[str, dict[str, str]] = {
    ERROR_NO_PROVIDERS: {
        "zh": "AI 未配置。请在 KVM 设置中设置 AI API Key。",
        "ja": "AI が未設定です。KVM 設定で AI API Key を設定してください。",
        "en": "AI is not configured. Please set your AI API Key in KVM Settings.",
    },
    ERROR_TIMEOUT: {
        "zh": "AI 请求超时，模型响应过慢。请尝试更换模型或稍后重试。",
        "ja": "AI リクエストがタイムアウトしました。モデルを変更するか、後で再試行してください。",
        "en": "AI request timed out. Try a different model or retry later.",
    },
    ERROR_CONNECT: {
        "zh": "无法连接 AI 服务，请检查网络或 API 地址。",
        "ja": "AI サービスに接続できません。ネットワークまたは API アドレスを確認してください。",
        "en": "Cannot reach AI service. Check your network or API endpoint.",
    },
    ERROR_EMPTY: {
        "zh": "AI 返回空结果，可能是模型暂时异常。请稍后重试或更换模型。",
        "ja": "AI が空の応答を返しました。しばらく待ってから再試行するか、モデルを変更してください。",
        "en": "AI returned an empty response. Try again later or switch models.",
    },
    ERROR_NO_TOOL_SUPPORT: {
        "zh": "当前模型不支持工具调用，已降级为分析模式。",
        "ja": "現在のモデルはツール呼び出しに対応していません。分析モードに切り替えました。",
        "en": "Current model does not support tool calls. Falling back to analysis mode.",
    },
    ERROR_FAILED: {
        "zh": "AI 请求失败，请稍后重试。",
        "ja": "AI リクエストに失敗しました。しばらくしてから再試行してください。",
        "en": "AI request failed. Please try again later.",
    },
}


def ai_error_message(code: str, lang: str = "en") -> str:
    """Return a localized user-facing message for an AI error code."""
    bucket = _AI_ERROR_MESSAGES.get(code) or _AI_ERROR_MESSAGES[ERROR_FAILED]
    return bucket.get(lang) or bucket.get("en") or code

# Stage timeouts — task-driven, model-agnostic
STAGE_TIMEOUT = {
    "decide": 30,
    "analyse": 60,
    "ocr": 90,
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
        response_format: dict | None = None,
    ) -> RouteResult:
        """Send history + tools to AI, get structured response with meta.

        Stateless: caller manages history.
        If cloud_prompt is provided (from kdcms), uses it instead of local prompt.
        response_format (also from kdcms) drives reasoning-tag stripping in the
        response parser, kept in sync with the prompt that produced it.
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
            response_format=response_format,
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
        response_format: dict | None = None,
    ) -> str:
        """Single-turn analysis/Q&A. Returns plain text on success.

        Raises AIError subclass (with `.code`) on router failure.
        """
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
            response_format=response_format,
        )
        _raise_from_route(result)

        text = result.response.text

        if self._memory and INTENT_ANALYSE.parser:
            parsed = INTENT_ANALYSE.parser(text)
            if isinstance(parsed, AnalysisResponse):
                await self._process_memory_ops(parsed.memory_ops)
                text = parsed.text

        text = (text or "").strip()
        if not text:
            raise AIEmptyError()
        return text

    async def ocr(
        self,
        screenshot_b64: str,
        lang: str = "en",
    ) -> str:
        """Extract all visible text from a screenshot.

        Returns plain text on success. Raises AIError on router failure.
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
        _raise_from_route(result)

        text = (result.response.text or "").strip()
        if not text:
            raise AIEmptyError()
        return text

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
