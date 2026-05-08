"""
P0-1 regression: /api/ai/models must not leak saved api_key to attacker URLs.

Covers two surfaces:

  1. ``_resolve_and_validate_base_url`` — the shared SSRF guard used by both
     /api/ai/test and /api/ai/models. Unit tests pin its rules so drift in
     one endpoint is caught at the function boundary.

  2. ``h_ai_models`` handler — integration tests through aiohttp that patch
     ``_fetch_provider_models`` to a spy, confirming what the handler *would*
     actually send outbound under each auth state.

The attacks we reject here:
  * Unauthenticated caller supplies ``base_url=https://evil.example`` +
    ``provider=openai`` hoping to receive the stored OpenAI key in the
    Authorization header. Pinned URL must override user input.
  * Unauthenticated caller supplies only ``provider=openai`` with no
    ``api_key``, hoping the handler falls back to ``cfg.ai.providers[*].api_key``.
    Fallback must be gated on ``request["authenticated"]``.
  * Any caller (auth or not) pointing ``base_url`` at a cloud metadata
    endpoint (169.254.169.254 et al).
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lib.config import AIConfig, Config, ProviderConfig
from lib.handlers import ai_config as aic


# ── Unit tests for the shared SSRF guard ────────────────────────────────────


class TestResolveAndValidateBaseURL:
    """Rules the guard must enforce. Tests are ordered by blast radius."""

    # 1. Pinned cloud providers ignore user input (the core P0-1 defence)

    def test_openai_pinned_url_wins_over_rogue_user_base(self):
        info = {"base_url": "https://api.openai.com/v1"}
        resolved, err = aic._resolve_and_validate_base_url(
            "https://evil.example/v1", "openai", info
        )
        assert err is None
        assert resolved == "https://api.openai.com/v1"

    def test_gemini_pinned_url_wins_over_metadata_host(self):
        info = {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}
        resolved, err = aic._resolve_and_validate_base_url(
            "http://169.254.169.254/latest", "gemini", info
        )
        assert err is None
        assert resolved == "https://generativelanguage.googleapis.com/v1beta/openai"

    def test_anthropic_pinned_url_wins_over_http_downgrade(self):
        info = {"base_url": "https://api.anthropic.com/v1"}
        resolved, err = aic._resolve_and_validate_base_url(
            "http://api.anthropic.com/v1", "anthropic", info
        )
        assert err is None
        assert resolved == "https://api.anthropic.com/v1"

    # 2. Metadata hosts are always rejected (even for non-pinned providers)

    def test_metadata_host_aws_rejected_for_custom_provider(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url(
            "https://169.254.169.254/latest", "custom", info
        )
        assert resolved is None
        assert err is not None
        assert "metadata" in err.lower()

    def test_metadata_host_gce_rejected_for_ollama(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url(
            "http://metadata.google.internal/computeMetadata/v1/", "ollama", info
        )
        assert resolved is None
        assert err is not None

    # 3. Link-local addresses are rejected even if not in the metadata list

    def test_link_local_ip_rejected(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url(
            "http://169.254.200.1/v1", "ollama", info
        )
        assert resolved is None
        assert err is not None
        assert "link-local" in err.lower()

    # 4. Scheme rules

    def test_custom_provider_rejects_http(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url(
            "http://my-company-llm.internal/v1", "custom", info
        )
        assert resolved is None
        assert err is not None
        assert "https" in err.lower()

    def test_custom_provider_accepts_https(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url(
            "https://my-company-llm.internal/v1", "custom", info
        )
        assert err is None
        assert resolved == "https://my-company-llm.internal/v1"

    def test_ollama_accepts_lan_http(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url(
            "http://192.168.1.50:11434/v1", "ollama", info
        )
        assert err is None
        assert resolved == "http://192.168.1.50:11434/v1"

    def test_custom_missing_base_url_rejected(self):
        info = {"base_url": ""}
        resolved, err = aic._resolve_and_validate_base_url("", "custom", info)
        assert resolved is None
        assert err is not None

    def test_empty_base_url_returns_none_for_pinned_provider_with_empty_info(self):
        # Defensive: if info came back without base_url (shouldn't happen in
        # prod since KNOWN_PROVIDERS ships one) the guard falls through.
        resolved, err = aic._resolve_and_validate_base_url("", "openai", {"base_url": ""})
        assert err is None
        assert resolved is None


# ── Integration tests for h_ai_models handler ───────────────────────────────


class _FetchSpy:
    """Record what ``_fetch_provider_models`` was asked to fetch."""

    def __init__(self):
        self.calls: list[dict] = []
        self.return_value: tuple[list[str], str | None] = (["model-a"], None)

    async def __call__(self, provider, info, base_url, api_key):
        self.calls.append({
            "provider": provider,
            "base_url": base_url,
            "api_key": api_key,
        })
        return self.return_value


def _build_app(authenticated: bool, saved_providers: list[ProviderConfig],
               fetch_spy: _FetchSpy) -> web.Application:
    """Spin up a minimal aiohttp app that registers ai_config routes.

    A middleware injects the ``authenticated`` flag — this mirrors how
    ``lib.middleware.auth_middleware`` annotates the request in production.
    """
    cfg = Config()
    cfg.ai = AIConfig(providers=saved_providers)

    @web.middleware
    async def _inject_auth(request, handler):
        request["authenticated"] = authenticated
        return await handler(request)

    app = web.Application(middlewares=[_inject_auth])
    app["cfg"] = cfg
    app["kvm"] = MagicMock()
    app["audit"] = MagicMock()
    app["providers"] = {}
    app["model_router"] = None
    app["kvmind_client"] = MagicMock()

    # Replace the outbound fetch with a spy so we never actually hit the network.
    app["_orig_fetch"] = aic._fetch_provider_models
    aic._fetch_provider_models = fetch_spy  # type: ignore[assignment]

    aic.register(app)
    return app


@pytest.fixture
async def spy_and_restore():
    spy = _FetchSpy()
    original = aic._fetch_provider_models
    try:
        yield spy
    finally:
        aic._fetch_provider_models = original  # type: ignore[assignment]


@pytest.fixture
async def unauth_client(spy_and_restore):
    spy = spy_and_restore
    saved = [
        ProviderConfig(name="openai", base_url="https://api.openai.com/v1",
                       api_key="sk-secret-stored", default_model="gpt-4"),
        ProviderConfig(name="ollama", base_url="http://192.168.1.50:11434/v1",
                       api_key="", default_model="llama3"),
    ]
    app = _build_app(authenticated=False, saved_providers=saved, fetch_spy=spy)
    async with TestClient(TestServer(app)) as client:
        yield client, spy


@pytest.fixture
async def auth_client(spy_and_restore):
    spy = spy_and_restore
    saved = [
        ProviderConfig(name="openai", base_url="https://api.openai.com/v1",
                       api_key="sk-secret-stored", default_model="gpt-4"),
        ProviderConfig(name="ollama", base_url="http://192.168.1.50:11434/v1",
                       api_key="", default_model="llama3"),
    ]
    app = _build_app(authenticated=True, saved_providers=saved, fetch_spy=spy)
    async with TestClient(TestServer(app)) as client:
        yield client, spy


class TestAIModelsSSRF:
    """Verify what the handler forwards outbound under each threat scenario."""

    async def test_unauth_rogue_base_for_custom_provider_is_blocked(self, unauth_client):
        """Custom provider + evil URL must not trigger any outbound fetch."""
        client, spy = unauth_client
        resp = await client.post("/api/ai/models", json={
            "provider": "custom",
            "base_url": "https://evil.example/v1",
            "api_key": "user-supplied",
        })
        # ``custom`` is not in KNOWN_PROVIDERS — handler rejects at the
        # provider lookup step, which also prevents any fetch.
        assert resp.status == 400
        assert spy.calls == []

    async def test_unauth_no_key_does_not_fall_back_to_saved(self, unauth_client):
        """Unauth caller without key must NOT inherit the stored OpenAI key."""
        client, spy = unauth_client
        resp = await client.post("/api/ai/models", json={
            "provider": "openai",
            # No api_key supplied, no base_url — before P0-1 fix the handler
            # would have read saved.api_key and sent it outbound.
        })
        # Requires-key + no key + no fallback → free_input_only response,
        # 200 with error=missing_api_key, zero outbound fetches.
        assert resp.status == 200
        body = await resp.json()
        assert body["free_input_only"] is True
        assert body["error"] == "missing_api_key"
        assert spy.calls == []

    async def test_unauth_rogue_base_for_pinned_provider_is_ignored(self, unauth_client):
        """Even if the caller supplies api_key + evil URL, pinned URL wins."""
        client, spy = unauth_client
        resp = await client.post("/api/ai/models", json={
            "provider": "openai",
            "base_url": "https://evil.example/v1",
            "api_key": "user-supplied-key",  # goes out, but to the pinned URL
        })
        assert resp.status == 200
        assert len(spy.calls) == 1
        call = spy.calls[0]
        # The critical assertion: outbound URL is the real OpenAI endpoint,
        # never the attacker-controlled one.
        assert call["base_url"] == "https://api.openai.com/v1"
        assert "evil.example" not in call["base_url"]
        # User-supplied key was used (that is expected — they opted in by
        # typing it). Saved key must NOT have been substituted.
        assert call["api_key"] == "user-supplied-key"

    async def test_auth_metadata_host_still_rejected(self, auth_client):
        """Auth session cannot unlock metadata host; SSRF guard is absolute."""
        client, spy = auth_client
        resp = await client.post("/api/ai/models", json={
            "provider": "ollama",  # non-pinned so user_base is consulted
            "base_url": "http://169.254.169.254/computeMetadata/",
        })
        assert resp.status == 400
        assert spy.calls == []

    async def test_auth_ollama_lan_is_allowed(self, auth_client):
        """Legit self-hosted ollama on LAN is still reachable."""
        client, spy = auth_client
        resp = await client.post("/api/ai/models", json={
            "provider": "ollama",
            "base_url": "http://192.168.1.50:11434/v1",
        })
        assert resp.status == 200
        assert len(spy.calls) == 1
        assert spy.calls[0]["base_url"] == "http://192.168.1.50:11434/v1"

    async def test_auth_openai_without_user_key_inherits_saved(self, auth_client):
        """Post-setup UI flow: admin opens settings, handler re-lists models
        using stored key without re-prompting. This is the legitimate use case
        that P0-1 must preserve for authenticated sessions."""
        client, spy = auth_client
        resp = await client.post("/api/ai/models", json={"provider": "openai"})
        assert resp.status == 200
        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["base_url"] == "https://api.openai.com/v1"
        # This is the opposite of the unauth test — saved key IS inherited.
        assert call["api_key"] == "sk-secret-stored"
