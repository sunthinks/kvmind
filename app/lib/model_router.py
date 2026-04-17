"""
KVMind AI Router v3 — Model-Agnostic Sequential Fallback

Routes AI requests through providers in priority order.
All providers use the same timeout, same flow, same validation.

Two-layer fallback:
  1. Transport: timeout / network error / HTTP error → try next
  2. Semantic: empty response when tools expected → try next

Final safety net: if ALL providers fail, returns a degraded
response instead of raising — WebSocket never breaks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai_provider import AIProvider, ProviderResponse

log = logging.getLogger(__name__)


# ── Result Types ────────────────────────────────────────────────────────────

@dataclass
class RouteMeta:
    """Observable system state — for logging/debug, not for decision-making."""
    provider_name: str
    model: str
    attempts: int
    fallback_used: bool


@dataclass
class RouteResult:
    """Response from router with metadata."""
    response: "ProviderResponse"
    meta: RouteMeta


# ── Exception ───────────────────────────────────────────────────────────────

class RouterError(Exception):
    """Raised internally when a single provider fails."""


# ── Router ──────────────────────────────────────────────────────────────────

class ModelRouter:
    """Routes AI requests to providers with automatic fallback.

    Providers dict order = priority. First provider is tried first.
    Timeout is unified — same for all providers, per-call override allowed.
    """

    def __init__(
        self,
        providers: dict[str, "AIProvider"],
        default_timeout: int = 120,
    ) -> None:
        self.providers = providers
        self.default_timeout = default_timeout

    async def send(
        self,
        system_prompt: str,
        messages: list,
        max_tokens: int = 4096,
        tools: list | None = None,
        timeout: int | None = None,
    ) -> RouteResult:
        """Send request through providers in order. Two-layer fallback.

        Returns RouteResult on success, or a degraded RouteResult if all fail.
        Raises RouterError if no providers are configured at all.
        """
        if not self.providers:
            raise RouterError("No AI providers configured")

        effective_timeout = timeout or self.default_timeout
        last_error: Exception | None = None
        attempt = 0

        for name, provider in self.providers.items():
            attempt += 1
            t0 = time.monotonic()
            try:
                resp = await provider.send(
                    system_prompt=system_prompt,
                    messages=messages,
                    model=provider.default_model,
                    max_tokens=max_tokens,
                    timeout=effective_timeout,
                    tools=tools,
                )
                latency = time.monotonic() - t0

                # ── Semantic validation ──
                if self._is_semantic_invalid(resp, tools):
                    log.warning(
                        "[Router] %s/%s: semantic invalid (%.1fs), fallback",
                        name, provider.default_model, latency,
                    )
                    last_error = RouterError(f"{name}: semantic invalid response")
                    continue

                log.info(
                    "[Router] %s/%s OK (%.1fs, text=%d, tools=%d)",
                    name, provider.default_model, latency,
                    len(resp.text), len(resp.tool_calls),
                )
                return RouteResult(
                    response=resp,
                    meta=RouteMeta(name, provider.default_model, attempt, attempt > 1),
                )

            except Exception as exc:
                latency = time.monotonic() - t0
                log.warning(
                    "[Router] %s/%s failed (%.1fs): %s",
                    name, provider.default_model, latency, exc,
                )
                last_error = exc

        # ── Final safety net: degraded response ──
        log.error(
            "[Router] All %d providers failed: %s", attempt, last_error,
        )
        from .ai_provider import ProviderResponse
        # Distinguish failure reason for customer-facing messaging
        is_tool_failure = (
            isinstance(last_error, RouterError)
            and "semantic invalid" in str(last_error)
        )
        if is_tool_failure:
            fallback_text = ""
        elif isinstance(last_error, asyncio.TimeoutError) or (
            last_error and "timeout" in str(last_error).lower()
        ):
            fallback_text = "AI 请求超时，模型响应过慢。请尝试更换模型或增加超时时间。"
        elif last_error and "connect" in str(last_error).lower():
            fallback_text = "无法连接 AI 服务，请检查网络连接和 API 地址。"
        else:
            fallback_text = f"AI 请求失败: {last_error}" if last_error else "AI 请求失败，请稍后再试。"
        return RouteResult(
            response=ProviderResponse(
                text=fallback_text,
                tool_calls=[],
                stop_reason="no_tool_support" if is_tool_failure else "error",
            ),
            meta=RouteMeta("none", "none", attempt, True),
        )

    @staticmethod
    def _is_semantic_invalid(resp: "ProviderResponse", tools: list | None) -> bool:
        """Semantic validation: detect empty/garbage responses.

        When tools are provided, valid responses are:
          1. Has tool_calls (executing actions)
          2. Has text without tool_calls (answering/completing)
        Invalid when:
          - Empty response (no text AND no tool_calls)
          - Text contains embedded tool JSON but no native tool_calls
            (model doesn't support function calling)
        """
        if not tools:
            return False
        if not resp.text and not resp.tool_calls:
            return True
        # Model wrote tool calls as JSON text instead of using native API
        if resp.text and not resp.tool_calls:
            tool_names = _extract_tool_names(tools)
            if tool_names and resp.has_embedded_tool_json(tool_names):
                return True
        return False


def _extract_tool_names(tools: list) -> set[str]:
    """Extract tool names from either portable or OpenAI format."""
    names: set[str] = set()
    for t in tools:
        if "name" in t:
            names.add(t["name"])
        elif isinstance(t.get("function"), dict):
            name = t["function"].get("name")
            if name:
                names.add(name)
    return names
