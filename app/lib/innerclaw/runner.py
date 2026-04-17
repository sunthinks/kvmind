"""
InnerClaw Runner v3 — Protocol-Driven Agentic Loop

Model-agnostic: all models follow the same pipeline.
AI output is untrusted — validated via protocol checks, not model hacks.

Self-correction: protocol violations trigger retry with error feedback.
Dedup: same violation type only retried once.

Usage:
    runner = Runner(kvm, kvmind, audit, mode="auto", lang="zh")
    async for event in runner.run("Install nginx"):
        await adapter.send_event(event.as_dict())
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from .budget import Budget
from .cloud_session import CloudSession
from .executor import Executor
from .guardrails import Guardrails
from .intent_gate import classify_intent, CONFIDENCE_THRESHOLD, INTENT_CHAT, _TOOL_INTENTS
from .memory import HistoryManager
from .observation import ObservationTracker
from .policy import ExecutionPolicy
from .protocol import ProtocolValidator
from .tools import (
    Action, ActionResult, INNERCLAW_TOOLS,
    build_tool_result_message, screenshot_hash,
)
from ..config import get_config
from ..kvm.base import NoVideoSignalError

log = logging.getLogger(__name__)

# Protocol: known tool names (for validation)
_KNOWN_TOOLS = {t["name"] for t in INNERCLAW_TOOLS}


# ── Event ────────────────────────────────────────────────────────────────────

class RunnerEvent:
    """Event emitted to the transport layer (adapters)."""

    def __init__(self, event: str, **data: object) -> None:
        self.event = event
        self.data = data

    def as_dict(self) -> dict:
        return {"event": self.event, **self.data}


# ── Runner ───────────────────────────────────────────────────────────────────

class Runner:
    """
    InnerClaw v3 — protocol-driven agentic loop.

    Three modes:
      - "ask":     Screenshot + analyse() → text response
      - "suggest": Screenshot + analyse() → advisory response
      - "auto":    Agentic loop: observe → decide → validate → execute → repeat
    """

    def __init__(
        self,
        kvm: object,
        ai_client: object,
        audit: object,
        mode: str = "auto",
        lang: str = "zh",
        gateway: object | None = None,
        trigger: str = "manual",
        internal_tools: dict | None = None,
    ) -> None:
        self._kvm = kvm
        self._ai = ai_client
        self._audit = audit
        self._mode = mode
        self._lang = lang
        self._guardrails = Guardrails()
        self._abort_event = asyncio.Event()
        self._executor = Executor(kvm, self._guardrails, gateway=gateway,
                                  abort_event=self._abort_event)
        self._policy = ExecutionPolicy()
        self._memory_mgr = HistoryManager()
        self._protocol = ProtocolValidator(_KNOWN_TOOLS)
        self._observer = ObservationTracker()
        self._cloud = CloudSession(gateway, trigger) if gateway else None
        self._internal_tools = internal_tools or {}
        self._abort = False
        self._confirm_future: asyncio.Future | None = None
        self._pending_confirm_action: dict | None = None

    def abort(self) -> None:
        self._abort = True
        self._abort_event.set()

    # ── Public entry ─────────────────────────────────────────────────────────

    async def run(
        self, instruction: str, context: list[dict] | None = None,
    ) -> AsyncIterator[RunnerEvent]:
        """Main entry. Yields events for the adapter."""
        self._context = context or []
        budget = Budget()
        budget.start()

        await self._audit.log("runner_start", {
            "instruction": instruction, "mode": self._mode,
        })

        try:
            effective_mode = self._mode

            # Intent Gate: AI-based classification (language-agnostic)
            if effective_mode == "auto":
                budget.use_ai_call()
                intent, confidence = await classify_intent(
                    self._ai._router, instruction,
                )
                if intent == INTENT_CHAT and confidence >= CONFIDENCE_THRESHOLD:
                    log.info(
                        "[IntentGate] CHAT detected, downgrading to suggest: conf=%.2f msg='%s'",
                        confidence, instruction[:60],
                    )
                    effective_mode = "suggest"
                else:
                    log.info(
                        "[IntentGate] Keeping auto mode: intent=%s conf=%.2f msg='%s'",
                        intent, confidence, instruction[:60],
                    )

            # Cloud session
            cloud_prompt = None
            if self._cloud:
                cloud_intent = "decide" if effective_mode == "auto" else "analyse"
                if await self._cloud.start(cloud_intent):
                    cloud_prompt = self._cloud.prompt

            if effective_mode == "auto":
                async for ev in self._agentic_loop(instruction, budget, cloud_prompt):
                    yield ev
            else:
                async for ev in self._advisory_response(instruction, budget, cloud_prompt):
                    yield ev

        except Exception as e:
            log.exception("Runner error")
            yield RunnerEvent("task_error", error=str(e))
        finally:
            await self._audit.log("runner_end", {
                "mode": self._mode,
                "actions": budget.actions_used,
                "ai_calls": budget.ai_calls_used,
            })

    # ── Advisory response (suggest/ask) ──────────────────────────────────────

    async def _advisory_response(
        self, instruction: str, budget: Budget, cloud_prompt: str | None = None,
    ) -> AsyncIterator[RunnerEvent]:
        """Single AI call for suggest/ask modes. No tools."""
        try:
            screenshot = await self._kvm.snapshot_b64()
            yield RunnerEvent("screenshot", screenshot=screenshot)
        except NoVideoSignalError as e:
            log.warning("Advisory: no video signal — continuing text-only (%s)", e.detail or "unknown")
            screenshot = None

        budget.use_ai_call()
        mode_desc = {
            "auto": "自动模式（可以直接操控远程计算机）",
            "suggest": "建议模式（只能观察和提供建议）",
        }
        mode_info = mode_desc.get(self._mode, self._mode)
        prompt = f"[当前模式: {mode_info}]\n\n{self._with_context(instruction)}"
        if screenshot is None:
            prompt = (
                "[注意：当前无视频信号，你无法看到屏幕。请仅基于用户文本作答；"
                "若用户问题需要看屏幕，请告知其连接 HDMI 后重试。]\n\n"
                + prompt
            )

        yield RunnerEvent("thinking", step=0)
        try:
            text = await self._ai.analyse(
                prompt, screenshot, lang=self._lang, cloud_prompt=cloud_prompt,
            )
            yield RunnerEvent("ai_text", text=text, step=0)
        except Exception as e:
            yield RunnerEvent("ai_text", text=f"分析失败: {e}", step=0)

        yield RunnerEvent("task_done", message="")

    # ── Agentic loop (auto mode) ─────────────────────────────────────────────

    async def _agentic_loop(
        self, instruction: str, budget: Budget, cloud_prompt: str | None = None,
    ) -> AsyncIterator[RunnerEvent]:
        """Protocol-driven observe->decide->validate->execute loop."""
        # Build initial user message with screenshot.
        # No video signal → agentic loop can't operate (no eyes), degrade to
        # advisory so the user still gets a helpful text response.
        try:
            screenshot = await self._kvm.snapshot_b64()
        except NoVideoSignalError as e:
            log.warning("Agentic: no video signal — degrading to advisory (%s)", e.detail or "unknown")
            async for ev in self._advisory_response(instruction, budget, cloud_prompt):
                yield ev
            return
        yield RunnerEvent("screenshot", screenshot=screenshot)

        content: list[dict] = [
            {"type": "text", "text": self._with_context(instruction)},
            {"type": "image_b64", "data": screenshot},
        ]
        history: list[dict] = [{"role": "user", "content": content}]
        current_ss = screenshot
        turn = 0

        while True:
            if self._abort:
                yield RunnerEvent("task_done", message="已中止")
                return

            history = self._memory_mgr.compress_if_needed(history)

            # AI decision
            if not budget.can_call_ai():
                yield RunnerEvent("task_error", error=budget.exhausted_reason())
                return
            budget.use_ai_call()
            turn += 1

            yield RunnerEvent("thinking", step=turn)
            result = await self._ai.decide(
                history, tools=INNERCLAW_TOOLS, lang=self._lang,
                cloud_prompt=cloud_prompt,
            )
            response = result.response
            meta = result.meta

            log.info(
                "[Runner] turn=%d via=%s/%s attempts=%d",
                turn, meta.provider_name, meta.model, meta.attempts,
            )

            # ── Degraded response detection ──
            if meta.provider_name == "none":
                if response.stop_reason == "no_tool_support":
                    _no_tool_msgs = {
                        "zh": "当前 AI 模型不支持工具调用，无法使用自动操作模式。\n请在 MyClaw 设置中切换到支持 Function Calling 的模型（如 Gemini、GPT-4o、Claude）。\n当前已切换到建议模式。",
                        "ja": "現在のAIモデルはツール呼び出しに対応していないため、自動操作モードは使用できません。\nMyClaw設定からFunction Calling対応モデルに切り替えてください。\n提案モードに切り替えました。",
                        "en": "Your AI model doesn't support tool calling — auto mode is unavailable.\nPlease switch to a model that supports Function Calling (e.g. Gemini, GPT-4o, Claude) in MyClaw Settings.\nSwitched to suggest mode.",
                    }
                    yield RunnerEvent("ai_text", text=_no_tool_msgs.get(self._lang, _no_tool_msgs["en"]), step=turn)
                    async for ev in self._advisory_response(instruction, budget, cloud_prompt):
                        yield ev
                    return
                if response.text:
                    yield RunnerEvent("ai_text", text=response.text, step=turn)
                yield RunnerEvent("task_error", error="All AI providers unavailable")
                return

            # ── Protocol validation (delegated to ProtocolValidator) ──
            if response.tool_calls:
                violation = self._protocol.validate_tool_calls(response.tool_calls)
                if violation:
                    correction = self._protocol.should_retry_violation(violation)
                    if correction is None:
                        yield RunnerEvent("task_error", error=f"AI protocol violation: {violation}")
                        return
                    history.append(response.to_history_message())
                    history.append(correction)
                    continue

            # ── No tool_calls ──
            if not response.tool_calls:
                if not response.text.strip():
                    retry_msg = self._protocol.handle_empty_response()
                    if retry_msg is None:
                        yield RunnerEvent("task_error", error="AI returned empty response")
                        return
                    history.append(retry_msg)
                    continue

                nudge = self._protocol.handle_text_only(turn)
                if nudge:
                    history.append(response.to_history_message())
                    history.append(nudge)
                    continue

                yield RunnerEvent("ai_text", text=response.text, step=turn)
                yield RunnerEvent("task_done", message=response.text)
                return

            # Valid tool calls — reset correction state
            self._protocol.reset_on_valid()

            if response.text:
                yield RunnerEvent("ai_text", text=response.text, step=turn)

            # Convert raw dicts to Action objects
            actions = [
                Action(id=tc["id"], name=tc["name"], input=tc["args"])
                for tc in response.tool_calls
            ]
            history.append(response.to_history_message())

            # ① Abort check on RAW actions (before optimize)
            abort_reason = self._policy.should_abort(history, actions, budget)
            if abort_reason:
                yield RunnerEvent("task_error", error=abort_reason)
                return

            # ② Optimize (dedup/debounce)
            optimized = self._policy.optimize(actions)

            # ②b Execute internal tools before KVM actions
            results: list[ActionResult] = []
            kvm_actions = []
            for action in optimized:
                if action.name in self._internal_tools:
                    budget.use_action()
                    yield RunnerEvent("action_start", action=action.name, args=action.input)
                    try:
                        res = await self._internal_tools[action.name](action.input)
                        ar = ActionResult(
                            tool_use_id=action.id, tool_name=action.name,
                            input=action.input,
                            status="error" if res.get("error") else "ok",
                            error=res.get("error"),
                        )
                    except Exception as exc:
                        ar = ActionResult(
                            tool_use_id=action.id, tool_name=action.name,
                            input=action.input, status="error", error=str(exc),
                        )
                    results.append(ar)
                    if ar.status == "ok":
                        yield RunnerEvent("action_done", action=action.name)
                    else:
                        yield RunnerEvent("action_error", action=action.name, error=ar.error or "")
                else:
                    kvm_actions.append(action)
            optimized = kvm_actions

            if not optimized:
                # Only internal tools — skip KVM execution, feed results back
                history.append(build_tool_result_message(results))
                continue

            # ③ Before-state = current screenshot (no extra PiKVM call)
            before_ss = current_ss
            before_hash = screenshot_hash(before_ss)

            # ④ Execute KVM actions

            if self._cloud and self._cloud.session_id:
                # ── MyClaw cloud-signed execution ──
                action_dicts = [{"name": a.name, "args": a.input} for a in optimized]
                level_err = self._cloud.check_action_level(action_dicts)
                if level_err:
                    yield RunnerEvent("task_error", error=level_err)
                    return

                signed = await self._cloud.sign_actions(action_dicts)

                for action in optimized:
                    if not budget.can_act():
                        yield RunnerEvent("task_error", error=budget.exhausted_reason())
                        return
                    budget.use_action()
                    yield RunnerEvent("action_start", action=action.name, args=action.input)

                batch_results = await self._executor.execute_signed_batch(
                    signed, self._cloud.device_uid, self._cloud.session_id,
                )

                if len(batch_results) < len(optimized):
                    reason = batch_results[0].get("reason", "Execution blocked") if batch_results else "Unknown"
                    yield RunnerEvent("task_error", error=reason)
                    return

                for action, res in zip(optimized, batch_results):
                    status = "blocked" if res.get("blocked") else res.get("status", "ok")
                    error = res.get("reason") or res.get("error")
                    ar = ActionResult(
                        tool_use_id=action.id, tool_name=action.name,
                        input=action.input, status=status, error=error,
                    )
                    ar.before_hash = before_hash
                    results.append(ar)
                    if status == "ok":
                        yield RunnerEvent("action_done", action=action.name)
                    else:
                        yield RunnerEvent("action_error", action=action.name, error=error or "")
            elif get_config().ai.allow_local_execution:
                # ── Local execution (dev/offline — no cloud signing) ──
                _VISUAL_ACTIONS = {"mouse_click", "mouse_double", "key_tap"}
                is_batch = len(optimized) > 2

                for i, action in enumerate(optimized):
                    if self._abort:
                        yield RunnerEvent("task_done", message="已中止")
                        return

                    if not budget.can_act():
                        yield RunnerEvent("task_error", error=budget.exhausted_reason())
                        return
                    budget.use_action()

                    yield RunnerEvent("action_start", action=action.name, args=action.input)

                    t0 = time.monotonic()
                    ar = await self._execute_action(action, history)

                    if ar.status == "pending_confirm":
                        yield RunnerEvent(
                            "confirm_required", action=action.name, args=action.input,
                        )
                        ar = await self._finish_confirm(action, history)

                    ar.duration_ms = int((time.monotonic() - t0) * 1000)
                    ar.before_hash = before_hash
                    results.append(ar)

                    if ar.status == "ok":
                        yield RunnerEvent("action_done", action=action.name)
                    else:
                        yield RunnerEvent("action_error", action=action.name, error=ar.error or "")

                    if (is_batch
                            and action.name in _VISUAL_ACTIONS
                            and i < len(optimized) - 1
                            and ar.status == "ok"):
                        await asyncio.sleep(0.15)
                        mid_ss = await self._kvm.snapshot_b64()
                        ar.screenshot = mid_ss

            else:
                yield RunnerEvent("task_error",
                                  error="Cloud session required for auto-execution. "
                                        "Enable allow_local_execution in config for offline/dev mode.")
                return

            # ⑤ Post-execution: visual stability detection (delegated to ObservationTracker)
            obs = await self._observer.capture_after(self._kvm, before_ss)
            yield RunnerEvent("screenshot", screenshot=obs.screenshot)
            self._observer.bind_to_results(results, obs)

            # ⑥ Stale detection
            stale_reason = self._policy.record_change(obs.change_type)
            if stale_reason:
                yield RunnerEvent("task_error", error=stale_reason)
                return

            # ⑦ Build tool_result message and append to history
            history.append(build_tool_result_message(results))
            current_ss = obs.screenshot

    # ── Action execution with safety ─────────────────────────────────────────

    async def _execute_action(
        self, action: Action, history: list[dict],
    ) -> ActionResult:
        """Execute one action through guardrails."""
        # Internal tools (non-KVM) — bypass executor
        if action.name in self._internal_tools:
            try:
                result = await self._internal_tools[action.name](action.input)
                return ActionResult(
                    tool_use_id=action.id, tool_name=action.name,
                    input=action.input,
                    status="error" if result.get("error") else "ok",
                    error=result.get("error"),
                )
            except Exception as exc:
                return ActionResult(
                    tool_use_id=action.id, tool_name=action.name,
                    input=action.input, status="error", error=str(exc),
                )

        action_dict = {"name": action.name, "args": action.input}
        result = await self._executor.execute(action_dict)

        if result.get("blocked"):
            if result.get("confirm"):
                loop = asyncio.get_running_loop()
                self._confirm_future = loop.create_future()
                self._pending_confirm_action = action_dict
                return ActionResult(
                    tool_use_id=action.id, tool_name=action.name,
                    input=action.input, status="pending_confirm",
                )
            else:
                return ActionResult(
                    tool_use_id=action.id, tool_name=action.name,
                    input=action.input, status="blocked",
                    error=result.get("reason", "Blocked by guardrails"),
                )

        if result.get("status") == "error":
            return ActionResult(
                tool_use_id=action.id, tool_name=action.name,
                input=action.input, status="error",
                error=result.get("error", "unknown"),
            )

        return ActionResult(
            tool_use_id=action.id, tool_name=action.name,
            input=action.input, status="ok",
        )

    async def _finish_confirm(
        self, action: Action, history: list[dict], timeout: float = 60,
    ) -> ActionResult:
        """Wait for user confirmation and execute or reject the action."""
        try:
            approved = await asyncio.wait_for(self._confirm_future, timeout=timeout)
        except asyncio.TimeoutError:
            log.info("[Runner] Confirm timed out after %.0fs", timeout)
            approved = False

        action_dict = self._pending_confirm_action

        if approved:
            history.append({
                "role": "user",
                "content": f"User approved dangerous action: {action.name}",
            })
            result = await self._executor.execute_force(action_dict)
            return ActionResult(
                tool_use_id=action.id, tool_name=action.name,
                input=action.input,
                status="ok" if result.get("status") == "ok" else "error",
                error=result.get("error"),
            )
        else:
            history.append({
                "role": "user",
                "content": f"User rejected dangerous action: {action.name}",
            })
            return ActionResult(
                tool_use_id=action.id, tool_name=action.name,
                input=action.input, status="rejected",
                error="User rejected dangerous operation",
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _with_context(self, instruction: str) -> str:
        """Build prompt by prepending chat context to instruction."""
        if not self._context:
            return instruction
        lines = []
        for m in self._context[-6:]:
            prefix = "用户" if m["role"] == "user" else "AI"
            lines.append(f"{prefix}: {m['content'][:200]}")
        return f"对话上下文:\n" + "\n".join(lines) + f"\n\n当前指令: {instruction}"

    def resolve_confirm(self, approved: bool) -> None:
        """Called by server.py when user responds to confirmation."""
        if self._confirm_future and not self._confirm_future.done():
            self._confirm_future.set_result(approved)
