"""Tests for lib/heartbeat.py — V6 signed heartbeat + 401 recovery path.

The key contracts:

  1. Outbound POST carries the five X-Device-* signature headers and
     no Bearer/Authorization header (V6 drops bearer auth).
  2. On 401, the first tick re-registers via ``mark_bootstrap_stale`` +
     ``ensure_bootstrapped`` and retries once.
  3. A second 401 raises the ``needs_reactivation`` banner via
     :func:`clear_activation`.
  4. On 200 we clear the recovery latch so the next 401 gets one more
     recovery attempt.
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from lib import heartbeat


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(bridge=SimpleNamespace(backend_url="https://kvmind.example"))


class _FakeResponse:
    def __init__(self, status: int, body: dict | None = None):
        self.status = status
        self._body = body or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._body


class _FakeSession:
    """Multi-response fake — pops responses off a queue per ``.post()`` call.

    The heartbeat's 401-recovery path issues two POSTs on a single tick
    (first attempt, re-bootstrap, retry), so a single-response fake would
    mis-represent the wire behaviour.
    """

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.post_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, *, headers=None, data=None, json=None, timeout=None):
        self.post_calls.append({"url": url, "headers": headers, "data": data,
                                 "json": json, "timeout": timeout})
        return self._responses.pop(0) if self._responses else _FakeResponse(500)


@pytest.fixture
def patch_identity(monkeypatch, tmp_path):
    """Pin UID, MAC/IP, and keypair path so signed headers are deterministic."""
    monkeypatch.setattr(heartbeat, "get_uid", lambda: "KVM-TEST-UID")
    monkeypatch.setattr(heartbeat, "_read_mac", lambda: "aa:bb:cc:dd:ee:ff")
    monkeypatch.setattr(heartbeat, "_read_ip", lambda: "192.0.2.1")
    from lib import device_keys as dk
    monkeypatch.setattr(dk, "KEY_PATH", str(tmp_path / "k"))
    monkeypatch.setattr(dk, "PUB_PATH", str(tmp_path / "p"))
    monkeypatch.setattr(dk, "_cached_sk", None)


@pytest.fixture
def install_session(monkeypatch):
    """Factory: install a ``_FakeSession`` with the given response queue."""
    def install(responses: list[_FakeResponse]) -> _FakeSession:
        session = _FakeSession(responses)
        monkeypatch.setattr(heartbeat.aiohttp, "ClientSession",
                            lambda *a, **kw: session)
        return session
    return install


class TestHeartbeatHappyPath:
    async def test_200_parses_subscription_and_clears_recovery_latch(
        self, tmp_state_db, patch_identity, install_session, monkeypatch
    ):
        """A successful tick must:
          (a) send a signed POST with no Bearer header,
          (b) walk _apply_subscription to flow features into cfg,
          (c) clear the ``heartbeat_recovered_bootstrap`` latch so the
              next 401 gets one more bootstrap attempt."""
        session = install_session([
            _FakeResponse(200, {
                "code": 200,
                "data": {
                    "claimState": "assigned", "entitlementState": "paid",
                    "features": {"tunnel": True, "messaging": False},
                },
            }),
        ])
        # Pre-set the latch as if a previous tick had bootstrapped — the
        # 200 success must knock it off.
        app = {"cfg": _build_cfg(), "heartbeat_recovered_bootstrap": True}
        monkeypatch.setattr(heartbeat, "save_config", lambda cfg: None)

        await heartbeat._one_tick(app, app["cfg"])

        assert "heartbeat_recovered_bootstrap" not in app
        # Signed headers present — Bearer absent.
        hdr = session.post_calls[0]["headers"]
        assert "X-Device-Sig" in hdr
        assert "X-Device-Uid" in hdr
        assert "Authorization" not in hdr
        # Pre-serialized body bytes (not aiohttp json= path).
        assert isinstance(session.post_calls[0]["data"], (bytes, bytearray))


class TestHeartbeat401Recovery:
    async def test_first_401_triggers_rebootstrap_then_succeeds(
        self, tmp_state_db, patch_identity, install_session, monkeypatch
    ):
        """401 on first POST → mark_bootstrap_stale + ensure_bootstrapped + retry.

        Recovery-success case: ensure_bootstrapped returns True and the
        immediate retry is 200 — the tick proceeds to apply subscription
        state, no banner raised.
        """
        session = install_session([
            _FakeResponse(401),
            _FakeResponse(200, {"code": 200, "data": {}}),
        ])
        boot_called = {"n": 0}
        async def _fake_bootstrap(cfg):
            boot_called["n"] += 1
            return True
        monkeypatch.setattr(heartbeat, "ensure_bootstrapped", _fake_bootstrap)
        stale_called = {"n": 0}
        def _fake_stale():
            stale_called["n"] += 1
        monkeypatch.setattr(heartbeat, "mark_bootstrap_stale", _fake_stale)
        monkeypatch.setattr(heartbeat, "save_config", lambda cfg: None)

        app = {"cfg": _build_cfg()}
        await heartbeat._one_tick(app, app["cfg"])

        assert boot_called["n"] == 1
        assert stale_called["n"] == 1
        assert len(session.post_calls) == 2
        # Banner not raised because recovery succeeded.
        assert tmp_state_db.get_needs_reactivation() is False

    async def test_second_401_raises_reactivation_banner(
        self, tmp_state_db, patch_identity, install_session, monkeypatch
    ):
        """Two 401s in a row → set needs_reactivation (server revoked us)."""
        session = install_session([
            _FakeResponse(401),
            _FakeResponse(401),  # retry still 401 — unrecoverable
        ])
        monkeypatch.setattr(heartbeat, "ensure_bootstrapped",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(heartbeat, "mark_bootstrap_stale", lambda: None)
        monkeypatch.setattr(heartbeat, "save_config", lambda cfg: None)

        app = {"cfg": _build_cfg()}
        await heartbeat._one_tick(app, app["cfg"])

        assert tmp_state_db.get_needs_reactivation() is True

    async def test_latch_prevents_infinite_rebootstrap_loop(
        self, tmp_state_db, patch_identity, install_session, monkeypatch
    ):
        """Once ``heartbeat_recovered_bootstrap`` is set, subsequent ticks
        must NOT re-run ensure_bootstrapped — otherwise the device would
        hammer /api/devices/bootstrap on every tick while kdcms is stuck
        returning 401."""
        install_session([_FakeResponse(401)])
        boot_called = {"n": 0}
        async def _fake_bootstrap(cfg):
            boot_called["n"] += 1
            return True
        monkeypatch.setattr(heartbeat, "ensure_bootstrapped", _fake_bootstrap)
        monkeypatch.setattr(heartbeat, "mark_bootstrap_stale", lambda: None)
        monkeypatch.setattr(heartbeat, "save_config", lambda cfg: None)

        # Latch already set — emulate "we tried recovery last tick, still 401".
        app = {"cfg": _build_cfg(), "heartbeat_recovered_bootstrap": True}
        await heartbeat._one_tick(app, app["cfg"])

        # No second recovery attempt this tick.
        assert boot_called["n"] == 0
        # Banner raised.
        assert tmp_state_db.get_needs_reactivation() is True


class TestTransportFailure:
    async def test_transport_error_silent_skip(
        self, tmp_state_db, patch_identity, monkeypatch
    ):
        """A DNS / TCP blip must not raise — the loop reschedules."""
        class _BlowUp:
            async def __aenter__(self): return self
            async def __aexit__(self, *e): return False
            def post(self, *a, **kw):
                raise RuntimeError("WAN down")
        monkeypatch.setattr(heartbeat.aiohttp, "ClientSession",
                            lambda *a, **kw: _BlowUp())

        app = {"cfg": _build_cfg()}
        # No exception should bubble out.
        await heartbeat._one_tick(app, app["cfg"])


class TestHeartbeatWake:
    async def test_wake_event_interrupts_long_sleep(self):
        app = {heartbeat.WAKE_EVENT_KEY: asyncio.Event()}

        async def _wake_soon():
            await asyncio.sleep(0.01)
            assert heartbeat.request_heartbeat_tick(app) is True

        wake_task = asyncio.create_task(_wake_soon())

        woke = await asyncio.wait_for(heartbeat._sleep_or_wake(app, 60), timeout=1)

        await wake_task
        assert woke is True
        assert app[heartbeat.WAKE_EVENT_KEY].is_set() is False

    async def test_wake_request_without_running_loop_is_noop(self):
        assert heartbeat.request_heartbeat_tick({}) is False


# ── helpers ────────────────────────────────────────────────────────────────


def _build_cfg() -> SimpleNamespace:
    """Build a cfg stub with the subscription attributes _apply_subscription reads/writes."""
    sub = SimpleNamespace(
        claim_state=None, entitlement_state=None, assigned_subscription_id=None,
        tunnel=False, messaging=False, ota=False, scheduled_tasks=False,
        myclaw_limit=5, myclaw_daily_limit=20, myclaw_max_action_level=1,
        synced_at=None,
    )
    return SimpleNamespace(
        bridge=SimpleNamespace(backend_url="https://kvmind.example"),
        subscription=sub,
    )
