"""Tests for Executor.execute_signed_batch — cloud signature verification path."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.innerclaw.executor import Executor
from lib.innerclaw.guardrails import Guardrails
from lib.myclaw_gateway import SignedActions


def _make_executor(verify_return=True, gateway=None, abort_event=None):
    """Build an Executor with mocked KVM and optional gateway + abort_event."""
    kvm = AsyncMock()
    guardrails = Guardrails()
    if gateway is None:
        gateway = MagicMock()
        gateway.verify_signature = MagicMock(return_value=verify_return)
    return Executor(kvm, guardrails, gateway=gateway, abort_event=abort_event), kvm


def _signed(actions, sig="ed25519:abc", ts=None, nonce="n1"):
    return SignedActions(
        actions=actions,
        signature=sig,
        timestamp=ts or int(time.time()),
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# Valid signature
# ---------------------------------------------------------------------------

class TestExecuteSignedBatchValid:
    @pytest.mark.asyncio
    async def test_single_action_ok(self):
        exe, kvm = _make_executor(verify_return=True)
        actions = [{"name": "mouse_click", "args": {"x": 50, "y": 50}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 1
        assert results[0]["status"] == "ok"
        kvm.mouse_click.assert_awaited_once_with(50, 50, "left")

    @pytest.mark.asyncio
    async def test_multiple_actions(self):
        exe, kvm = _make_executor(verify_return=True)
        actions = [
            {"name": "mouse_click", "args": {"x": 10, "y": 20}},
            {"name": "type_text", "args": {"text": "hello"}},
            {"name": "wait", "args": {"seconds": 0.1}},
        ]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 3
        assert all(r["status"] == "ok" for r in results)

    @pytest.mark.asyncio
    async def test_key_combo_action(self):
        # P1-H: Executor now dispatches key_combo as individual key_press calls so that
        # an abort can interrupt between keys. We assert press-all-then-release-all.
        exe, kvm = _make_executor(verify_return=True)
        actions = [{"name": "key_combo", "args": {"keys": ["ctrl", "c"]}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["status"] == "ok"
        # Expected sequence: press ctrl, press c, release c, release ctrl
        calls = [args for args, _ in kvm.key_press.call_args_list]
        assert calls == [("ctrl", True), ("c", True), ("c", False), ("ctrl", False)]


# ---------------------------------------------------------------------------
# Invalid / missing signature
# ---------------------------------------------------------------------------

class TestExecuteSignedBatchInvalid:
    @pytest.mark.asyncio
    async def test_invalid_signature_blocked(self):
        exe, kvm = _make_executor(verify_return=False)
        actions = [{"name": "mouse_click", "args": {"x": 50, "y": 50}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 1
        assert results[0]["blocked"] is True
        assert "Invalid signature" in results[0]["reason"]
        kvm.mouse_click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_gateway_blocked(self):
        """Executor without gateway should block all signed batch calls."""
        kvm = AsyncMock()
        exe = Executor(kvm, Guardrails(), gateway=None)
        actions = [{"name": "type_text", "args": {"text": "test"}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["blocked"] is True
        kvm.type_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Expired signature
# ---------------------------------------------------------------------------

class TestExecuteSignedBatchExpired:
    @pytest.mark.asyncio
    async def test_expired_timestamp_blocked(self):
        exe, kvm = _make_executor(verify_return=True)
        actions = [{"name": "mouse_click", "args": {"x": 50, "y": 50}}]
        # Timestamp 120 seconds ago — beyond the 60s window
        signed = _signed(actions, ts=int(time.time()) - 120)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["blocked"] is True
        assert "Expired" in results[0]["reason"]
        kvm.mouse_click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_timestamp_ok(self):
        exe, kvm = _make_executor(verify_return=True)
        actions = [{"name": "mouse_click", "args": {"x": 50, "y": 50}}]
        # Timestamp 30 seconds ago — within window
        signed = _signed(actions, ts=int(time.time()) - 30)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["status"] == "ok"


# ---------------------------------------------------------------------------
# Guardrails interaction
# ---------------------------------------------------------------------------

class TestExecuteSignedBatchGuardrails:
    @pytest.mark.asyncio
    async def test_dangerous_action_blocked_by_guardrails(self):
        """Power action should be blocked by guardrails (requires confirmation)."""
        exe, kvm = _make_executor(verify_return=True)
        actions = [{"name": "power", "args": {"action": "off"}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["blocked"] is True
        kvm.power_action.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_action_blocked(self):
        exe, kvm = _make_executor(verify_return=True)
        actions = [{"name": "delete_everything", "args": {}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["blocked"] is True

    @pytest.mark.asyncio
    async def test_mixed_valid_and_blocked(self):
        """First action OK, second blocked by guardrails."""
        exe, kvm = _make_executor(verify_return=True)
        actions = [
            {"name": "mouse_click", "args": {"x": 50, "y": 50}},
            {"name": "power", "args": {"action": "reboot"}},
        ]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 2
        assert results[0]["status"] == "ok"
        assert results[1]["blocked"] is True


# ---------------------------------------------------------------------------
# Dispatch error handling
# ---------------------------------------------------------------------------

class TestExecuteSignedBatchErrors:
    @pytest.mark.asyncio
    async def test_dispatch_error_captured(self):
        exe, kvm = _make_executor(verify_return=True)
        kvm.mouse_click.side_effect = RuntimeError("HID timeout")
        actions = [{"name": "mouse_click", "args": {"x": 50, "y": 50}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert results[0]["status"] == "error"
        assert "HID timeout" in results[0]["error"]


# ---------------------------------------------------------------------------
# P1-H: Cooperative abort — abort_event must interrupt the batch immediately
# (between actions) and mid-type_text / mid-key_combo.
# ---------------------------------------------------------------------------

class TestExecuteSignedBatchAbort:
    @pytest.mark.asyncio
    async def test_abort_before_first_action(self):
        """Abort already set when batch starts: no actions run, all marked aborted."""
        abort = asyncio.Event()
        abort.set()
        exe, kvm = _make_executor(verify_return=True, abort_event=abort)
        actions = [
            {"name": "mouse_click", "args": {"x": 1, "y": 1}},
            {"name": "mouse_click", "args": {"x": 2, "y": 2}},
        ]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 2
        assert all(r["status"] == "aborted" for r in results)
        kvm.mouse_click.assert_not_awaited()
        # release_all should fire so any lingering HID state is cleaned up.
        kvm.release_all.assert_awaited()

    @pytest.mark.asyncio
    async def test_abort_between_actions(self):
        """Abort set AFTER first action runs: first is ok, rest are aborted."""
        abort = asyncio.Event()
        exe, kvm = _make_executor(verify_return=True, abort_event=abort)

        # Flip abort as a side-effect of the first mouse_click so the second iteration
        # sees the abort at its top-of-loop check.
        async def click_and_abort(*_a, **_kw):
            abort.set()
        kvm.mouse_click.side_effect = click_and_abort

        actions = [
            {"name": "mouse_click", "args": {"x": 1, "y": 1}},
            {"name": "mouse_click", "args": {"x": 2, "y": 2}},
            {"name": "mouse_click", "args": {"x": 3, "y": 3}},
        ]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 3
        assert results[0]["status"] == "ok"
        assert results[1]["status"] == "aborted"
        assert results[2]["status"] == "aborted"
        # Only the first click made it through.
        assert kvm.mouse_click.await_count == 1

    @pytest.mark.asyncio
    async def test_abort_mid_type_text(self):
        """
        Abort set before type_text begins: the per-char loop raises CancelledError
        on the very first char, resulting in zero kvm.type_text calls and the
        action marked aborted (not error).
        """
        abort = asyncio.Event()
        abort.set()  # abort before dispatching
        exe, kvm = _make_executor(verify_return=True, abort_event=abort)

        actions = [{"name": "type_text", "args": {"text": "hello"}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        # Pre-iteration abort short-circuits the whole batch — type_text never runs.
        assert len(results) == 1
        assert results[0]["status"] == "aborted"
        kvm.type_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_abort_mid_type_text_after_first_char(self):
        """
        Abort fires AFTER the first char is typed. The per-char abort check should
        break the loop before the remaining chars go out, and the action is marked
        aborted. The executor dispatches one char per kvm.type_text call.
        """
        abort = asyncio.Event()
        exe, kvm = _make_executor(verify_return=True, abort_event=abort)

        call_count = {"n": 0}
        async def type_one_and_abort(_ch):
            call_count["n"] += 1
            if call_count["n"] == 1:
                abort.set()
        kvm.type_text.side_effect = type_one_and_abort

        actions = [{"name": "type_text", "args": {"text": "hello"}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 1
        assert results[0]["status"] == "aborted"
        # Exactly one char made it out (the one that triggered the abort).
        assert kvm.type_text.await_count == 1
        # release_all must have fired for HID cleanup.
        kvm.release_all.assert_awaited()

    @pytest.mark.asyncio
    async def test_abort_mid_key_combo_releases_pressed_keys(self):
        """
        If abort fires after 'ctrl' is pressed but before 'c', the executor must
        still release 'ctrl' in the finally block — otherwise ctrl would be left
        held down on the target machine.
        """
        abort = asyncio.Event()
        exe, kvm = _make_executor(verify_return=True, abort_event=abort)

        async def press_first_then_abort(key, pressed):
            # Only set abort AFTER ctrl-press so the loop sees it before pressing 'c'.
            if key == "ctrl" and pressed:
                abort.set()
        kvm.key_press.side_effect = press_first_then_abort

        actions = [{"name": "key_combo", "args": {"keys": ["ctrl", "c"]}}]
        signed = _signed(actions)

        results = await exe.execute_signed_batch(signed, "KVM-001", "sess-1")

        assert len(results) == 1
        assert results[0]["status"] == "aborted"
        # We must see: press ctrl, (abort detected, skip c press), release ctrl.
        calls = [args for args, _ in kvm.key_press.call_args_list]
        assert ("ctrl", True) in calls
        assert ("ctrl", False) in calls
        # 'c' must NEVER have been pressed.
        assert ("c", True) not in calls
