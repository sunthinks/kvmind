"""
KVMind AI Router v4 — Structured Failure Contract

Routes AI requests through providers in priority order.
All providers use the same timeout, same flow, same validation.

Two-layer fallback:
  1. Transport: timeout / network error / HTTP error → try next
  2. Semantic: empty response or embedded tool JSON → try next

Failure contract:
  On success: RouteResult with real text/tool_calls and provider_name != "none"
  On failure: RouteResult with empty text, provider_name="none",
              meta.error_code set to a canonical code.
  Never raises on runtime failures. Never injects user-facing text into response.
  Error code → user message mapping happens at handler layer (i18n-aware).
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


# ── Canonical error codes (stable API — do not rename without sweeping callers) ──

ERROR_NO_PROVIDERS = "no_providers"       # No AI backend configured
ERROR_TIMEOUT = "ai_timeout"              # All providers timed out
ERROR_CONNECT = "ai_connect"              # Network / DNS / SSL to provider
ERROR_EMPTY = "ai_empty"                  # Provider returned empty response
ERROR_NO_TOOL_SUPPORT = "ai_no_tools"     # Model can't use native function-calling
ERROR_FAILED = "ai_failed"                # Generic provider failure


# ── Result Types ────────────────────────────────────────────────────────────

@dataclass
class RouteMeta:
    """Observable routing state. error_code is only set on failure."""
    provider_name: str
    model: str
    attempts: int
    fallback_used: bool
    error_code: str | None = None


@dataclass
class RouteResult:
    """Response from router with metadata."""
    response: "ProviderResponse"
    meta: RouteMeta

    @property
    def ok(self) -> bool:
        return self.meta.error_code is None


# ── Exception ───────────────────────────────────────────────────────────────

class RouterError(Exception):
    """Internal marker for provider-level failures within the router loop."""


# ── Router ──────────────────────────────────────────────────────────────────

class ModelRouter:
    """Routes AI requests to providers with automatic fallback.

    Providers dict order = priority. First provider is tried first.
    Timeout is unified — same for all providers, per-call override allowed.

    send() never raises on runtime errors — failures are returned as
    RouteResult with meta.error_code set. Callers branch on result.ok.
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
        response_format: dict | None = None,
    ) -> RouteResult:
        """Send request through providers in order. Two-layer fallback.

        Always returns RouteResult. On failure, response.text="" and
        meta.error_code is a canonical code (see module-level constants).
        """
        if not self.providers:
            return self._failure_result(0, ERROR_NO_PROVIDERS)

        effective_timeout = timeout or self.default_timeout
        last_error_code: str | None = None
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
                    response_format=response_format,
                )
                latency = time.monotonic() - t0

                invalid_code = self._semantic_invalid_code(resp, tools)
                if invalid_code:
                    log.warning(
                        "[Router] %s/%s: %s (%.1fs), fallback",
                        name, provider.default_model, invalid_code, latency,
                    )
                    last_error_code = invalid_code
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
                last_error_code = self._classify_transport_error(exc)
                log.warning(
                    "[Router] %s/%s failed (%.1fs, code=%s): %s",
                    name, provider.default_model, latency, last_error_code, exc,
                )

        log.error("[Router] All %d providers failed (code=%s)", attempt, last_error_code)
        return self._failure_result(attempt, last_error_code or ERROR_FAILED)

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _failure_result(attempts: int, code: str) -> RouteResult:
        from .ai_provider import ProviderResponse
        return RouteResult(
            response=ProviderResponse(text="", tool_calls=[], stop_reason="error"),
            meta=RouteMeta("none", "none", attempts, True, error_code=code),
        )

    @staticmethod
    def _classify_transport_error(exc: Exception) -> str:
        if isinstance(exc, asyncio.TimeoutError):
            return ERROR_TIMEOUT
        msg = str(exc).lower()
        if "timeout" in msg:
            return ERROR_TIMEOUT
        if "connect" in msg or "dns" in msg or "ssl" in msg or "network" in msg:
            return ERROR_CONNECT
        return ERROR_FAILED

    @staticmethod
    def _semantic_invalid_code(resp: "ProviderResponse", tools: list | None) -> str | None:
        """Return error code if response is semantically invalid, else None.

        Always-invalid: empty response (no text AND no tool_calls).
        Tool-context-invalid: text contains embedded tool JSON but no native
          tool_calls — model doesn't support function calling.
        """
        if not resp.text and not resp.tool_calls:
            return ERROR_EMPTY
        if tools and resp.text and not resp.tool_calls:
            tool_names = _extract_tool_names(tools)
            if tool_names and resp.has_embedded_tool_json(tool_names):
                return ERROR_NO_TOOL_SUPPORT
        return None


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
