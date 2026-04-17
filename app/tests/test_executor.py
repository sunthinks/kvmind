"""Tests for innerclaw/executor.py — Action dispatch & abort-aware wait."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.fixture
def executor(mock_kvm, guardrails):
    return Executor(mock_kvm, guardrails)


@pytest.fixture
def abort_event():
    return asyncio.Event()


@pytest.fixture
def executor_with_abort(mock_kvm, guardrails, abort_event):
    return Executor(mock_kvm, guardrails, abort_event=abort_event)


# ── Basic dispatch ──────────────────────────────────────────────────────────

class TestDispatch:
    def test_type_text(self, executor, mock_kvm):
        result = run(executor.execute({"name": "type_text", "args": {"text": "hello"}}))
        assert result["status"] == "ok"
        mock_kvm.type_text.assert_called_once_with("hello")

    def test_key_tap(self, executor, mock_kvm):
        result = run(executor.execute({"name": "key_tap", "args": {"key": "Enter"}}))
        assert result["status"] == "ok"
        mock_kvm.key_tap.assert_called_once_with("Enter")

    def test_key_combo(self, executor, mock_kvm):
        result = run(executor.execute({"name": "key_combo", "args": {"keys": ["Control", "C"]}}))
        assert result["status"] == "ok"
        mock_kvm.key_combo.assert_called_once_with("Control", "C")

    def test_mouse_click(self, executor, mock_kvm):
        result = run(executor.execute({"name": "mouse_click", "args": {"x": 50, "y": 50, "button": "left"}}))
        assert result["status"] == "ok"
        mock_kvm.mouse_click.assert_called_once_with(50, 50, "left")

    def test_mouse_click_default_button(self, executor, mock_kvm):
        result = run(executor.execute({"name": "mouse_click", "args": {"x": 10, "y": 20}}))
        assert result["status"] == "ok"
        mock_kvm.mouse_click.assert_called_once_with(10, 20, "left")

    def test_mouse_double(self, executor, mock_kvm):
        result = run(executor.execute({"name": "mouse_double", "args": {"x": 30, "y": 40}}))
        assert result["status"] == "ok"
        mock_kvm.mouse_double_click.assert_called_once_with(30, 40)

    def test_scroll(self, executor, mock_kvm):
        result = run(executor.execute({"name": "scroll", "args": {"delta_y": -3}}))
        assert result["status"] == "ok"
        mock_kvm.mouse_wheel.assert_called_once_with(0, -3)

    def test_unknown_action_returns_error(self, executor):
        result = run(executor.execute({"name": "nonexistent", "args": {}}))
        assert result["status"] == "error"
        assert "Unknown action" in result["error"]

    def test_screenshot_is_noop(self, executor):
        result = run(executor.execute({"name": "screenshot", "args": {}}))
        assert result["status"] == "ok"


# ── Guardrails ──────────────────────────────────────────────────────────────

class TestGuardrails:
    def test_blocked_action_not_dispatched(self, mock_kvm, guardrails):
        guardrails.check = MagicMock(return_value={"blocked": True, "reason": "dangerous"})
        executor = Executor(mock_kvm, guardrails)

        result = run(executor.execute({"name": "type_text", "args": {"text": "rm -rf /"}}))
        assert result.get("blocked") is True
        mock_kvm.type_text.assert_not_called()

    def test_execute_force_skips_guardrails(self, mock_kvm, guardrails):
        guardrails.check = MagicMock(return_value={"blocked": True, "reason": "dangerous"})
        executor = Executor(mock_kvm, guardrails)

        result = run(executor.execute_force({"name": "type_text", "args": {"text": "forced"}}))
        assert result["status"] == "ok"
        mock_kvm.type_text.assert_called_once_with("forced")


# ── Wait with abort ─────────────────────────────────────────────────────────

class TestWait:
    def test_normal_wait_completes(self, executor):
        start = time.monotonic()
        result = run(executor.execute({"name": "wait", "args": {"seconds": 0.1}}))
        elapsed = time.monotonic() - start

        assert result["status"] == "ok"
        assert elapsed >= 0.09  # at least ~0.1s

    def test_wait_capped_at_max(self, executor):
        """Wait requesting 30s should be capped at MAX_WAIT_SECONDS (10)."""
        start = time.monotonic()
        # Use a very short cap for test speed
        executor.MAX_WAIT_SECONDS = 0.2
        result = run(executor.execute({"name": "wait", "args": {"seconds": 30}}))
        elapsed = time.monotonic() - start

        assert result["status"] == "ok"
        assert elapsed < 1.0  # Should not wait 30s

    def test_abort_interrupts_wait(self, executor_with_abort, abort_event):
        """Setting abort_event should interrupt a wait by raising CancelledError.

        Production semantic (executor.py): when abort_event fires during a wait,
        _dispatch raises asyncio.CancelledError("Aborted during wait"), which
        execute() re-raises after releasing HID. Callers must observe the
        cancellation — no synthetic {"status": "error"} wrapper."""
        async def test():
            # Schedule abort after 50ms
            async def set_abort():
                await asyncio.sleep(0.05)
                abort_event.set()
            asyncio.create_task(set_abort())

            start = time.monotonic()
            with pytest.raises(asyncio.CancelledError) as exc_info:
                await executor_with_abort.execute(
                    {"name": "wait", "args": {"seconds": 5}}
                )
            elapsed = time.monotonic() - start

            assert elapsed < 1.0  # Should not wait 5s
            assert "Aborted" in str(exc_info.value)

        run(test())

    def test_wait_without_abort_event(self, executor):
        """Executor without abort_event uses plain sleep."""
        start = time.monotonic()
        result = run(executor.execute({"name": "wait", "args": {"seconds": 0.1}}))
        elapsed = time.monotonic() - start

        assert result["status"] == "ok"
        assert elapsed >= 0.09

    def test_wait_default_seconds(self, executor):
        """Wait with no seconds arg defaults to 1.0 (capped for test)."""
        executor.MAX_WAIT_SECONDS = 0.1
        result = run(executor.execute({"name": "wait", "args": {}}))
        assert result["status"] == "ok"


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
        gateway = MagicMock()
        gateway.verify_signature = MagicMock(return_value=True)
        executor = Executor(mock_kvm, guardrails, gateway=gateway)

        signed = MagicMock()
        signed.actions = [{"name": "type_text", "args": {"text": "x"}}]
        signed.signature = "valid"
        signed.timestamp = time.time() - 120  # 2 minutes ago, > 60s
        signed.nonce = "abc"

        results = run(executor.execute_signed_batch(signed, "dev-1", "sess-1"))
        assert results[0].get("blocked") is True
        assert "Expired" in results[0].get("reason", "")

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
        mock_kvm.type_text.assert_called_once_with("hello")
        mock_kvm.key_tap.assert_called_once_with("Enter")
