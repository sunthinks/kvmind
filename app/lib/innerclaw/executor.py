"""
InnerClaw Runner v5 — Executor

Dispatches validated actions to KVM device through Guardrails.
execute()             — manual HID, guardrails only
execute_signed_batch() — AI auto execution, requires cloud signature
"""
from __future__ import annotations

import asyncio
import logging
import time

from .guardrails import Guardrails

log = logging.getLogger(__name__)


class Executor:
    """
    Execute actions on KVM device after passing Guardrails checks.
    """

    MAX_WAIT_SECONDS = 10.0
    _HID_ACTIONS = {"mouse_click", "mouse_double", "type_text", "key_tap", "key_combo"}

    def __init__(self, kvm: object, guardrails: Guardrails, gateway: object | None = None,
                 abort_event: asyncio.Event | None = None) -> None:
        self._kvm = kvm
        self._guardrails = guardrails
        self._gateway = gateway
        self._abort_event = abort_event

    async def execute(self, action: dict) -> dict:
        """
        Execute a single action.
        Returns {"status": "ok"} or {"blocked": True, ...} or {"status": "error", ...}.
        """
        # Guardrails check first
        check = self._guardrails.check(action)
        if check.get("blocked"):
            return check

        name = action.get("name", "")
        args = action.get("args", {})

        try:
            await self._dispatch(name, args)
            return {"status": "ok"}
        except asyncio.CancelledError as e:
            log.info("[Executor] Action %s aborted: %s", name, e)
            await self._release_hid_if_needed(name)
            raise
        except Exception as e:
            log.error("[Executor] Action %s failed: %s", name, e)
            await self._release_hid_if_needed(name)
            return {"status": "error", "error": str(e)}

    async def execute_force(self, action: dict) -> dict:
        """Execute without guardrails check (for user-confirmed dangerous actions)."""
        name = action.get("name", "")
        args = action.get("args", {})
        try:
            await self._dispatch(name, args)
            return {"status": "ok"}
        except asyncio.CancelledError:
            await self._release_hid_if_needed(name)
            raise
        except Exception as e:
            log.error("[Executor] Force action %s failed: %s", name, e)
            await self._release_hid_if_needed(name)
            return {"status": "error", "error": str(e)}

    async def execute_signed_batch(self, signed, device_uid: str, session_id: str) -> list:
        """Unique AI execution entry — requires valid cloud signature."""
        # P1-7: forward customer_id so the verifier can reconstruct the new payload
        # layout. Legacy responses set customer_id=None; the verifier falls through
        # to the old layout in that case during the 30-day migration window.
        if not self._gateway or not self._gateway.verify_signature(
            signed.actions, signed.signature, device_uid, session_id,
            signed.timestamp, signed.nonce,
            customer_id=getattr(signed, "customer_id", None),
        ):
            return [{"blocked": True, "reason": "Invalid signature"}]
        if abs(time.time() - signed.timestamp) > 60:
            return [{"blocked": True, "reason": "Expired signature"}]

        results = []
        for action in signed.actions:
            # P1-H: Cooperative abort BEFORE every action. Previously only the `wait`
            # branch honored abort_event, so an abort arriving between two actions
            # still burned through the rest of the batch. Now we short-circuit and
            # mark remaining actions so the caller sees exactly where we stopped.
            if self._abort_event and self._abort_event.is_set():
                remaining = len(signed.actions) - len(results)
                for _ in range(remaining):
                    results.append({"status": "aborted", "reason": "session aborted"})
                await self._release_all_safely()
                log.info("[Executor] Signed batch aborted mid-flight at action #%d/%d",
                         len(results) - remaining + 1, len(signed.actions))
                return results

            check = self._guardrails.check(action)
            if check.get("blocked"):
                results.append(check)
                continue
            try:
                await self._dispatch(action.get("name", ""), action.get("args", {}))
                results.append({"status": "ok"})
            except asyncio.CancelledError:
                # P1-H: Raised by type_text/key_combo when abort_event fires mid-iteration.
                # Record as aborted (not error) so callers distinguish user-cancel from failure.
                await self._release_hid_if_needed(action.get("name", ""))
                if self._abort_event and self._abort_event.is_set():
                    results.append({"status": "aborted", "reason": "aborted mid-action"})
                    remaining = len(signed.actions) - len(results)
                    for _ in range(remaining):
                        results.append({"status": "aborted", "reason": "session aborted"})
                    return results
                raise
            except Exception as e:
                log.error("[Executor] Signed action %s failed: %s", action.get("name"), e)
                await self._release_hid_if_needed(action.get("name", ""))
                results.append({"status": "error", "error": str(e)})
        return results

    async def _release_hid_if_needed(self, name: str) -> None:
        if name not in self._HID_ACTIONS:
            return
        await self._release_all_safely()

    async def _release_all_safely(self) -> None:
        """Best-effort release of any pressed HID controls — never raises."""
        release_all = getattr(self._kvm, "release_all", None)
        if not callable(release_all):
            return
        try:
            await release_all()
        except Exception as exc:
            log.warning("[Executor] HID release_all failed: %s", exc)

    async def _dispatch(self, name: str, args: dict) -> None:
        """Map action name to KVM backend method."""
        kvm = self._kvm
        abort = self._abort_event

        if name == "mouse_click":
            await kvm.mouse_click(args["x"], args["y"], args.get("button", "left"))
        elif name == "mouse_double":
            await kvm.mouse_double_click(args["x"], args["y"])
        elif name == "mouse_move":
            await kvm.mouse_move(args["x"], args["y"])
        elif name == "scroll":
            await kvm.mouse_wheel(args.get("delta_x", 0), args.get("delta_y", 0))
        elif name == "type_text":
            # P1-H: Dispatch char-by-char instead of handing the full string to kvm.type_text.
            # The backend iterates chars internally with ~30ms per-char sleep, so a 200-char
            # string would take ~6s with no chance to abort mid-typing. Polling abort_event
            # between chars makes abort effectively instant (≤ one-char latency).
            for ch in args.get("text", ""):
                if abort and abort.is_set():
                    raise asyncio.CancelledError("aborted mid-type_text")
                await kvm.type_text(ch)
        elif name == "key_tap":
            await kvm.key_tap(args["key"])
        elif name == "key_combo":
            # P1-H: Press keys one at a time with abort checks, then ALWAYS release in reverse
            # in the finally — otherwise an abort between "press Ctrl" and "press Alt" would
            # leak Ctrl-held state to the OS. This mirrors the default base-class semantics
            # but adds the per-key abort gate.
            keys = list(args.get("keys", []))
            pressed: list[str] = []
            try:
                for k in keys:
                    if abort and abort.is_set():
                        raise asyncio.CancelledError("aborted mid-key_combo")
                    await kvm.key_press(k, True)
                    await asyncio.sleep(0.02)
                    pressed.append(k)
                await asyncio.sleep(0.02)
            finally:
                for k in reversed(pressed):
                    try:
                        await asyncio.shield(kvm.key_press(k, False))
                        await asyncio.sleep(0.02)
                    except Exception as exc:
                        log.warning("[Executor] key_combo release %s failed: %s", k, exc)
        elif name == "power":
            await kvm.power_action(args["action"])
        elif name == "screenshot":
            pass  # handled by the harness loop
        elif name == "wait":
            seconds = min(float(args.get("seconds", 1.0)), self.MAX_WAIT_SECONDS)
            if abort:
                try:
                    await asyncio.wait_for(abort.wait(), timeout=seconds)
                    raise asyncio.CancelledError("Aborted during wait")
                except asyncio.TimeoutError:
                    pass  # Normal: wait completed without abort
            else:
                await asyncio.sleep(seconds)
        else:
            raise ValueError(f"Unknown action: {name}")
