"""Tests for the HTTP → :mod:`lib.errors` → WS-code mapping across three layers.

The plan's correctness claim (docs/plan#HTTP↔异常映射总表) asserts a strict
relation:

    HTTP status + X-Device-Sig-Error header  →  GatewayError subclass  →  WS error code

If any layer drifts, the UI shows the wrong CTA for a real device failure.
We test each stage in isolation and then as a pipeline.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aiohttp
import pytest

from lib.errors import (
    AuthError,
    GatewayError,
    NetworkError,
    PolicyError,
    QuotaError,
)
from lib import myclaw_gateway as mg
from lib.handlers.websocket import _gateway_error_payload


# ── Layer 1: HTTP → exception  (MyClawGateway._raise_for_status) ────────────


class _Resp:
    """Minimal stand-in for aiohttp.ClientResponse with just the fields
    :func:`_raise_for_status` reads (status + headers)."""

    def __init__(self, status: int, headers: dict | None = None):
        self.status = status
        self.headers = headers or {}


class TestRaiseForStatus:
    def test_2xx_is_noop(self):
        # No exception must bubble out on success — caller parses the body.
        mg._raise_for_status(_Resp(200), {"ok": True})
        mg._raise_for_status(_Resp(204), {})

    def test_401_without_sig_error_defaults_to_invalid_signature(self):
        with pytest.raises(AuthError) as exc:
            mg._raise_for_status(_Resp(401), {})
        assert exc.value.reason == "invalid_signature"

    def test_401_unknown_device_uid(self):
        with pytest.raises(AuthError) as exc:
            mg._raise_for_status(
                _Resp(401, {"X-Device-Sig-Error": "unknown_device_uid"}), {}
            )
        assert exc.value.reason == "unknown_device_uid"

    def test_401_replay_detected(self):
        with pytest.raises(AuthError) as exc:
            mg._raise_for_status(
                _Resp(401, {"X-Device-Sig-Error": "replay_detected"}), {}
            )
        assert exc.value.reason == "replay_detected"

    def test_401_signature_expired_maps_to_network_clock_skew(self):
        """The only 401 that routes through NetworkError (clock-skew CTA)."""
        with pytest.raises(NetworkError) as exc:
            mg._raise_for_status(
                _Resp(401, {"X-Device-Sig-Error": "signature_expired"}), {}
            )
        assert exc.value.reason == "clock_skew"

    def test_403_maps_to_policy_error(self):
        with pytest.raises(PolicyError) as exc:
            mg._raise_for_status(
                _Resp(403), {"code": "schedule_not_allowed"}
            )
        assert exc.value.code == "schedule_not_allowed"

    def test_403_without_code_still_raises_policy(self):
        with pytest.raises(PolicyError) as exc:
            mg._raise_for_status(_Resp(403), {})
        assert exc.value.code == "forbidden"

    def test_429_maps_to_quota_error(self):
        with pytest.raises(QuotaError) as exc:
            mg._raise_for_status(_Resp(429),
                                 {"retryAfter": 30, "usageCount": 5, "usageLimit": 5})
        assert exc.value.retry_after == 30
        assert exc.value.usage_count == 5
        assert exc.value.usage_limit == 5

    def test_5xx_maps_to_network_server_error(self):
        for s in (500, 502, 503, 504):
            with pytest.raises(NetworkError) as exc:
                mg._raise_for_status(_Resp(s), {})
            assert exc.value.reason == "server_error"

    def test_unexpected_4xx_maps_to_network_server_error(self):
        """A 418 or 404 isn't auth/policy/quota — surface as server_error so
        we don't mis-diagnose it as a client-side auth problem."""
        with pytest.raises(NetworkError) as exc:
            mg._raise_for_status(_Resp(418), {})
        assert exc.value.reason == "server_error"


# ── Layer 2: exception → WS payload (_gateway_error_payload) ───────────────


class TestGatewayErrorPayload:
    def test_auth_error_uniform_device_unbound_code(self):
        """invalid_signature / unknown_device_uid / replay all → 'device_unbound'.

        UX rule: the user's action is always the same — re-activate. Showing
        three different error codes would confuse non-technical users.
        """
        for reason in ("invalid_signature", "unknown_device_uid", "replay"):
            payload = _gateway_error_payload(AuthError(reason=reason), "r1", "en")
            assert payload["code"] == "device_unbound"
            assert payload["reason"] == reason
            assert payload["type"] == "error"

    def test_network_clock_skew_has_distinct_cta_message(self):
        """clock_skew must render the NTP-fix message, not 'service unavailable'."""
        payload = _gateway_error_payload(
            NetworkError(reason="clock_skew"), "r1", "en"
        )
        assert payload["code"] == "myclaw_offline"
        assert payload["reason"] == "clock_skew"
        # NTP hint present — the whole reason clock_skew is distinct.
        assert "NTP" in payload["message"] or "clock" in payload["message"].lower()

    def test_network_unreachable_vs_server_error_message(self):
        p1 = _gateway_error_payload(NetworkError(reason="unreachable"), "r1", "en")
        p2 = _gateway_error_payload(NetworkError(reason="server_error"), "r1", "en")
        assert p1["code"] == "myclaw_offline"
        assert p2["code"] == "myclaw_offline"
        # Distinct messages — the UI may log them separately for diagnostics.
        assert p1["message"] != p2["message"]

    def test_quota_error_carries_retry_after(self):
        payload = _gateway_error_payload(
            QuotaError(retry_after=45, usage_count=5, usage_limit=5), "r1", "en"
        )
        assert payload["code"] == "myclaw_rate_limit"
        assert payload["retry_after"] == 45
        assert "5/5" in payload["message"] or "5" in payload["message"]

    def test_policy_error_prefixed_with_myclaw_forbidden(self):
        payload = _gateway_error_payload(
            PolicyError(code="schedule_not_allowed"), "r1", "en"
        )
        assert payload["code"] == "myclaw_forbidden_schedule_not_allowed"

    def test_policy_error_unknown_code_falls_back_to_raw_slug(self):
        """A policy slug kdcms adds in the future should still produce a
        non-empty UX code, not blank-drop the error."""
        payload = _gateway_error_payload(
            PolicyError(code="hypothetical_future_code"), "r1", "en"
        )
        assert payload["code"] == "myclaw_forbidden_hypothetical_future_code"
        assert payload["message"]  # non-empty default

    def test_base_gateway_error_falls_back_to_offline(self):
        """An abstract GatewayError shouldn't silently drop the turn."""
        payload = _gateway_error_payload(GatewayError("odd"), "r1", "en")
        assert payload["code"] == "myclaw_offline"

    def test_lang_fallback_to_english_when_missing(self):
        """Unknown lang code (future addition) must not crash the dispatcher."""
        payload = _gateway_error_payload(
            QuotaError(retry_after=1, usage_count=1, usage_limit=1),
            "r1", "fr",  # not in our template
        )
        assert payload["code"] == "myclaw_rate_limit"
        assert payload["message"]  # rendered something (English default)


# ── Layer 3: pipeline — end-to-end HTTP→WS mapping for each scenario ──────


class TestHttpToWsPipeline:
    """Integration-ish: for each HTTP outcome, what does the WS see?

    Each assertion below corresponds to one row in the plan's mapping table.
    If this suite needs editing, the plan table also needs editing — they
    are the same contract restated in two formats.
    """

    def _pipeline(self, resp: _Resp, body: dict, lang: str = "en") -> dict:
        try:
            mg._raise_for_status(resp, body)
        except GatewayError as e:
            return _gateway_error_payload(e, "run1", lang)
        return {}

    def test_401_unknown_device_uid_yields_device_unbound(self):
        p = self._pipeline(_Resp(401, {"X-Device-Sig-Error": "unknown_device_uid"}), {})
        assert p["code"] == "device_unbound"

    def test_401_signature_expired_yields_offline_clock_skew(self):
        p = self._pipeline(_Resp(401, {"X-Device-Sig-Error": "signature_expired"}), {})
        assert p["code"] == "myclaw_offline"
        assert p["reason"] == "clock_skew"

    def test_429_yields_myclaw_rate_limit(self):
        p = self._pipeline(_Resp(429), {"retryAfter": 10, "usageCount": 3, "usageLimit": 5})
        assert p["code"] == "myclaw_rate_limit"
        assert p["retry_after"] == 10

    def test_403_budget_exceeded_yields_forbidden_budget(self):
        p = self._pipeline(_Resp(403), {"code": "budget_exceeded"})
        assert p["code"] == "myclaw_forbidden_budget_exceeded"

    def test_503_yields_offline_server_error(self):
        p = self._pipeline(_Resp(503), {})
        assert p["code"] == "myclaw_offline"
        assert p["reason"] == "server_error"


# ── MyClawGateway outbound: uses signature headers, not Bearer ────────────


class TestGatewaySignsRequests:
    """The gateway must attach the five X-Device-* headers. A regression here
    (e.g. accidental re-introduction of a Bearer header) would cause kdcms
    DeviceSigFilter to passthrough and 401 every call."""

    async def test_start_session_posts_signed_headers(self, monkeypatch, tmp_path):
        cfg = SimpleNamespace(bridge=SimpleNamespace(backend_url="https://kvmind.example"))

        # Isolate keypair to tmp so the test doesn't touch /etc/kdkvm.
        from lib import device_keys as dk
        monkeypatch.setattr(dk, "KEY_PATH", str(tmp_path / "k"))
        monkeypatch.setattr(dk, "PUB_PATH", str(tmp_path / "p"))
        monkeypatch.setattr(dk, "_cached_sk", None)

        # Capture outbound headers / body without a real HTTP hit.
        captured = {}

        class _Resp:
            status = 200
            headers = {}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def json(self):
                return {"allowed": True, "sessionId": "s1", "prompt": "p", "policy": {}}

        class _Session:
            def post(self, url, *, data=None, headers=None, timeout=None):
                captured["url"] = url
                captured["data"] = data
                captured["headers"] = headers
                return _Resp()

        async def _get(): return _Session()
        monkeypatch.setattr(mg, "_get_shared_session", _get)

        gw = mg.MyClawGateway(cfg=cfg, device_uid="KVM-TEST",
                              public_key_path=str(tmp_path / "nonexistent.pub"))
        await gw.start_session(trigger="manual", intent="analyse")

        # The five canonical headers are present; Bearer must not be.
        for h in ("X-Device-Uid", "X-Device-Ts", "X-Device-Nonce",
                  "X-Device-Sig", "X-Device-Sig-Version"):
            assert h in captured["headers"]
        assert "Authorization" not in captured["headers"]
        assert captured["headers"]["X-Device-Uid"] == "KVM-TEST"
        # And data was sent as pre-serialized bytes, not the aiohttp json= path.
        assert isinstance(captured["data"], (bytes, bytearray))
