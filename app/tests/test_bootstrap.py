"""Tests for lib/bootstrap.py — idempotent pubkey registration with kdcms.

This is the only device-side step that runs *before* the Ed25519 identity
chain works (the call itself is permitAll on kdcms because we don't yet
have a verifiable signature). Getting the idempotency right is load-bearing:

  - The device restarts often (OTA, power-cycle) and must NOT re-POST the
    pubkey on every boot (unnecessary IP-rate-limit pressure, logs, etc).
  - But when kdcms loses the row (migration / ops rollback), the device
    must re-register — the heartbeat 401 recovery path calls
    :func:`mark_bootstrap_stale` + :func:`ensure_bootstrapped` in sequence.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from lib import bootstrap


def _cfg(backend_url: str = "https://kvmind.example") -> SimpleNamespace:
    return SimpleNamespace(bridge=SimpleNamespace(backend_url=backend_url))


class _FakeResponse:
    def __init__(self, *, status: int, body: str = ""):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.post_call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    def post(self, url, *, data=None, headers=None, timeout=None, ssl=None):
        self.post_call = {"url": url, "data": data, "headers": headers,
                          "timeout": timeout, "ssl": ssl}
        return self._response


@pytest.fixture
def fake_session(monkeypatch):
    created = {}

    def install(response: _FakeResponse) -> _FakeSession:
        session = _FakeSession(response)
        created["session"] = session
        monkeypatch.setattr(bootstrap.aiohttp, "ClientSession",
                            lambda *a, **kw: session)
        return session

    return install


@pytest.fixture
def patch_identity(monkeypatch, tmp_path):
    """Pin UID + keypair path so bootstrap posts deterministic bytes."""
    monkeypatch.setattr(bootstrap, "get_uid", lambda: "KVM-TEST")
    from lib import device_keys as dk
    key = tmp_path / "device_ed25519.key"
    pub = tmp_path / "device_ed25519.pub"
    monkeypatch.setattr(dk, "KEY_PATH", str(key))
    monkeypatch.setattr(dk, "PUB_PATH", str(pub))
    monkeypatch.setattr(dk, "_cached_sk", None)


class TestEnsureBootstrapped:
    async def test_short_circuits_when_flag_set(self, tmp_state_db, patch_identity, monkeypatch):
        """If ``kv.bootstrap_done == 'true'`` we must NOT hit the network.

        The whole point of the flag is saving a request per boot — a call
        slipping through on every startup would defeat the rate-limit budget.
        """
        tmp_state_db.kv_set("bootstrap_done", "true")
        # Make a ClientSession construction explode — proves no network touch.
        called = {"n": 0}
        def boom(*a, **kw):
            called["n"] += 1
            raise RuntimeError("network must not be used")
        monkeypatch.setattr(bootstrap.aiohttp, "ClientSession", boom)

        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is True
        assert called["n"] == 0

    async def test_first_boot_registers_and_sets_flag(
        self, tmp_state_db, patch_identity, fake_session
    ):
        fake_session(_FakeResponse(status=200, body='{"uid":"KVM-TEST","status":"registered"}'))
        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is True
        assert tmp_state_db.kv_get("bootstrap_done") == "true"

    async def test_201_also_counts_as_success(
        self, tmp_state_db, patch_identity, fake_session
    ):
        """kdcms currently returns 200 but 201 is the stricter REST reading.
        Accepting both avoids a breakage if ops returns to 201."""
        fake_session(_FakeResponse(status=201))
        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is True
        assert tmp_state_db.kv_get("bootstrap_done") == "true"

    async def test_409_exists_is_noop_success(
        self, tmp_state_db, patch_identity, fake_session
    ):
        """Eventual world: kdcms may return 409 if the row was already created.
        Today it returns 200, but the bootstrap path must not regress to a
        transient failure on 409 if kdcms ever restores that response shape."""
        # Current implementation treats 409 as non-200 (failure) — encode that,
        # so a future behaviour change has to explicitly update this test.
        fake_session(_FakeResponse(status=409, body="duplicate"))
        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is False
        # Flag NOT set — retry next boot.
        assert (tmp_state_db.kv_get("bootstrap_done") or "") != "true"

    async def test_server_5xx_does_not_set_flag(
        self, tmp_state_db, patch_identity, fake_session
    ):
        fake_session(_FakeResponse(status=500, body="oops"))
        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is False
        # Must NOT set the flag on failure — otherwise a boot-time transient
        # would permanently latch the device into "bootstrapped" while kdcms
        # actually dropped the registration.
        assert (tmp_state_db.kv_get("bootstrap_done") or "") != "true"

    async def test_400_does_not_set_flag(
        self, tmp_state_db, patch_identity, fake_session
    ):
        fake_session(_FakeResponse(status=400, body='{"error":"invalid_uid"}'))
        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is False
        assert (tmp_state_db.kv_get("bootstrap_done") or "") != "true"

    async def test_transport_error_does_not_set_flag(
        self, tmp_state_db, patch_identity, monkeypatch
    ):
        class _BlowUp:
            async def __aenter__(self): return self
            async def __aexit__(self, *e): return False
            def post(self, *a, **kw):
                raise RuntimeError("DNS down")
        monkeypatch.setattr(bootstrap.aiohttp, "ClientSession",
                            lambda *a, **kw: _BlowUp())
        ok = await bootstrap.ensure_bootstrapped(_cfg())
        assert ok is False
        assert (tmp_state_db.kv_get("bootstrap_done") or "") != "true"

    async def test_payload_shape_matches_dto(
        self, tmp_state_db, patch_identity, fake_session
    ):
        """kdcms DeviceBootstrapRequest: {uid, publicKey, algorithm[, macAddress]}.

        Serialization is the canonical form we also use to compute body hash;
        field name drift from the DTO would either 400 on kdcms or diverge
        from the hashed body on any future signed bootstrap variant.
        """
        import json
        session = fake_session(_FakeResponse(status=200))
        await bootstrap.ensure_bootstrapped(_cfg())

        body_bytes = session.post_call["data"]
        assert isinstance(body_bytes, (bytes, bytearray))
        payload = json.loads(body_bytes.decode("utf-8"))
        assert payload["uid"] == "KVM-TEST"
        assert payload["algorithm"] == "ed25519"
        assert "BEGIN PUBLIC KEY" in payload["publicKey"]

        headers = session.post_call["headers"]
        assert headers["Content-Type"] == "application/json"


class TestMarkBootstrapStale:
    def test_clears_flag(self, tmp_state_db):
        tmp_state_db.kv_set("bootstrap_done", "true")
        bootstrap.mark_bootstrap_stale()
        assert tmp_state_db.kv_get("bootstrap_done") is None

    def test_safe_when_never_set(self, tmp_state_db):
        # Absent key must not raise.
        bootstrap.mark_bootstrap_stale()
        assert tmp_state_db.kv_get("bootstrap_done") is None
