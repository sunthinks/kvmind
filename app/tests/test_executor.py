"""Tests for innerclaw/executor.py — cloud-signed batch execution.

The executor's only public entry point is ``execute_signed_batch`` — all AI
auto-execution must pass through cloud signature verification (Ed25519 +
nonce + freshness) before any HID action reaches the KVM backend. There is
intentionally no local-execution path to test.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.innerclaw.executor import Executor
from lib.innerclaw.guardrails import Guardrails


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def mock_kvm():
    kvm = AsyncMock()
    kvm.type_text = AsyncMock()
    kvm.key_tap = AsyncMock()
    kvm.key_combo = AsyncMock()
    kvm.mouse_click = AsyncMock()
    kvm.mouse_double_click = AsyncMock()
    kvm.mouse_move = AsyncMock()
    kvm.mouse_wheel = AsyncMock()
    kvm.power_action = AsyncMock()
    return kvm


@pytest.fixture
def guardrails():
    g = MagicMock(spec=Guardrails)
    g.check = MagicMock(return_value={})  # not blocked
    return g


# ── Signed batch ────────────────────────────────────────────────────────────

class TestSignedBatch:
    def test_invalid_signature_blocks(self, mock_kvm, guardrails):
        gateway = MagicMock()
        gateway.verify_signature = MagicMock(return_value=False)
        executor = Executor(mock_kvm, guardrails, gateway=gateway)

        signed = MagicMock()
        signed.actions = [{"name": "type_text", "args": {"text": "x"}}]
        signed.signature = "bad"
        signed.timestamp = time.time()
        signed.nonce = "abc"

        results = run(executor.execute_signed_batch(signed, "dev-1", "sess-1"))
        assert results[0].get("blocked") is True

    def test_expired_signature_blocks(self, mock_kvm, guardrails):
        # Freshness enforcement lives inside gateway.verify_signature
        # (SIGNATURE_MAX_AGE_SECONDS). We simulate the gateway rejecting a
        # stale timestamp by returning False, and assert the executor
        # surfaces a block with "Invalid signature" — there is no separate
        # expiration path in the executor anymore (see executor.py docstring).
        gateway = MagicMock()
        gateway.verify_signature = MagicMock(return_value=False)
        executor = Executor(mock_kvm, guardrails, gateway=gateway)

        signed = MagicMock()
        signed.actions = [{"name": "type_text", "args": {"text": "x"}}]
        signed.signature = "valid-but-stale"
        signed.timestamp = time.time() - 600  # 10 minutes ago — past 300s window
        signed.nonce = "abc"

        results = run(executor.execute_signed_batch(signed, "dev-1", "sess-1"))
        assert results[0].get("blocked") is True
        assert "Invalid signature" in results[0].get("reason", "")

    def test_valid_signed_batch_executes(self, mock_kvm, guardrails):
        gateway = MagicMock()
        gateway.verify_signature = MagicMock(return_value=True)
        executor = Executor(mock_kvm, guardrails, gateway=gateway)

        signed = MagicMock()
        signed.actions = [
            {"name": "type_text", "args": {"text": "hello"}},
            {"name": "key_tap", "args": {"key": "Enter"}},
        ]
        signed.signature = "valid"
        signed.timestamp = time.time()
        signed.nonce = "abc"

        results = run(executor.execute_signed_batch(signed, "dev-1", "sess-1"))
        assert len(results) == 2
        assert all(r["status"] == "ok" for r in results)
        # P1-H per-char dispatch: "hello" → 5 separate type_text calls.
        assert [c.args[0] for c in mock_kvm.type_text.call_args_list] == list("hello")
        mock_kvm.key_tap.assert_called_once_with("Enter")
