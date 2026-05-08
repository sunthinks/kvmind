"""WebSocket handlers — agent event stream and MyClaw chat."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

import aiohttp
from aiohttp import web

from ..innerclaw import Runner
from ..innerclaw.adapters.bridge import WebBridgeAdapter
from ..ai_provider import is_tool_noise
from ..errors import AuthError, GatewayError, NetworkError, PolicyError, QuotaError
from ..model_router import ERROR_FAILED, ERROR_NO_PROVIDERS
from ..middleware import validate_session, SESSION_COOKIE
from .helpers import ai_error_message, json_response

log = logging.getLogger("kvmind.handlers.websocket")


# ── V6 unified GatewayError → WS payload dispatch ──────────────────────────

_POLICY_MSG_TPLS = {
    "schedule_not_allowed": {
        "zh": "定时任务需要 Pro 订阅",
        "ja": "スケジュールタスクにはProが必要です",
        "en": "Scheduled tasks require Pro",
    },
    "subscription_expired": {
        "zh": "订阅已过期，请续费",
        "ja": "サブスクリプション期限切れ",
        "en": "Subscription expired",
    },
    "budget_exceeded": {
        "zh": "本轮操作预算已用尽",
        "ja": "操作予算超過",
        "en": "Operation budget exceeded",
    },
}

_NETWORK_MSG_TPLS = {
    "unreachable": {"zh": "MyClaw 服务暂时不可用", "ja": "MyClaw サービス一時利用不可", "en": "MyClaw service unavailable"},
    "server_error": {"zh": "MyClaw 云端错误", "ja": "MyClaw クラウドエラー", "en": "MyClaw cloud error"},
    "clock_skew": {"zh": "设备时钟异常，请检查 NTP", "ja": "デバイスの時計がずれています。NTP を確認してください", "en": "Device clock drift — check NTP"},
}


def _gateway_error_payload(exc: "GatewayError", run_id: str, lang: str) -> dict:
    """Translate a :class:`GatewayError` into the WS payload dict.

    The mapping is deliberately spelled out as a single ``match`` so a
    reviewer can see every code at once and so adding a new error shape
    means touching exactly one function. The returned dict is ready for
    ``ws.send_json`` — no additional fields required.
    """
    match exc:
        case AuthError():
            # invalid_signature / unknown_device_uid / replay all surface the
            # same CTA: prompt re-activation. The concrete reason is logged
            # server-side (kdcms) and client-side (log line above) but the
            # WS code is uniform — the user's action is identical.
            msg = {
                "zh": "设备未绑定，请重新激活",
                "ja": "デバイス未連携です。再連携してください",
                "en": "Device unbound — please re-activate",
            }
            return {
                "type": "error", "run_id": run_id,
                "code": "device_unbound",
                "reason": exc.reason,
                "message": msg.get(lang, msg["en"]),
            }
        case NetworkError():
            msg_tpl = _NETWORK_MSG_TPLS.get(exc.reason, _NETWORK_MSG_TPLS["unreachable"])
            return {
                "type": "error", "run_id": run_id,
                "code": "myclaw_offline",
                "reason": exc.reason,
                "message": msg_tpl.get(lang, msg_tpl["en"]),
            }
        case QuotaError():
            msg_tpl = {
                "zh": f"MyClaw 使用已达上限（{exc.usage_count}/{exc.usage_limit}），{exc.retry_after}秒后重试",
                "ja": f"MyClaw 使用制限に達しました（{exc.usage_count}/{exc.usage_limit}）、{exc.retry_after}秒後にリトライ",
                "en": f"MyClaw rate limit reached ({exc.usage_count}/{exc.usage_limit}), retry in {exc.retry_after}s",
            }
            return {
                "type": "error", "run_id": run_id,
                "code": "myclaw_rate_limit",
                "message": msg_tpl.get(lang, msg_tpl["en"]),
                "retry_after": exc.retry_after,
            }
        case PolicyError():
            default = {
                "zh": f"操作被拒绝: {exc.code}",
                "ja": f"拒否されました: {exc.code}",
                "en": f"Denied: {exc.code}",
            }
            msg_tpl = _POLICY_MSG_TPLS.get(exc.code, default)
            return {
                "type": "error", "run_id": run_id,
                "code": f"myclaw_forbidden_{exc.code}",
                "message": msg_tpl.get(lang, msg_tpl["en"]),
            }
        case _:
            # Base GatewayError — unlikely (only concrete subclasses raise)
            # but we fall back to the generic offline shape so the WS never
            # ends a turn with an uncaught-error silent-drop.
            return {
                "type": "error", "run_id": run_id,
                "code": "myclaw_offline",
                "message": str(exc),
            }


def register(app: dict) -> None:
    """Register WebSocket routes on the aiohttp app."""

    hub = app["hub"]
    kvm = app["kvm"]
    audit = app["audit"]
    chat_store = app["chat_store"]
    gateway = app.get("gateway")

    # ── WebSocket: agent event stream ────────────────────────────────────────

    async def ws_agent(req: web.Request) -> web.WebSocketResponse:
        # Verify auth via cookie before upgrading
        token = req.cookies.get(SESSION_COOKIE, "")
        if not validate_session(token):
            return web.Response(status=401, text="Unauthorized")

        ws = web.WebSocketResponse()
        await ws.prepare(req)
        hub.add(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    pass
        finally:
            hub.remove(ws)
        return ws

    # ── WebSocket: MyClaw chat ────────────────────────────────────────────────

    async def ws_chat(req: web.Request) -> web.WebSocketResponse:
        """MyClaw chat interface — InnerClaw agentic loop."""
        # Auth check
        token = req.cookies.get(SESSION_COOKIE, "")
        if not validate_session(token):
            return web.Response(status=401, text="Unauthorized")

        ws = web.WebSocketResponse(max_msg_size=64 * 1024, protocols=["innerclaw.v1"])
        await ws.prepare(req)
        session_id = uuid.uuid4().hex
        log.info("[MyClaw Chat] Session %s connected (protocol=%s)", session_id, ws.ws_protocol)

        # Initialize chat session (history is managed by Runner, not kvmind)
        await chat_store.create_session(session_id)

        adapter = WebBridgeAdapter(ws)
        current_runner: Optional[Runner] = None
        runner_task: Optional[asyncio.Task] = None
        current_run_id: Optional[str] = None

        async def _release_hid(reason: str) -> None:
            release_all = getattr(kvm, "release_all", None)
            if not callable(release_all):
                return
            try:
                await release_all()
            except Exception as exc:
                log.warning("[MyClaw Chat] HID release_all failed after %s: %s", reason, exc)

        async def _run_runner(runner: Runner, instruction: str, run_id: str, lang: str, context: list[dict] | None = None) -> None:
            """Run the Runner in a background task so WS loop stays responsive."""
            nonlocal current_runner
            first_ai_text_saved = False
            last_ai_text = ""
            try:
                async for event in runner.run(instruction, context=context):
                    if ws.closed:
                        break
                    ev_dict = event.as_dict()
                    ev_dict["run_id"] = run_id
                    # Save to chat_store: only plan/analysis (first) and summary (last)
                    if ev_dict.get("event") == "ai_text" and ev_dict.get("text"):
                        if not first_ai_text_saved:
                            await chat_store.save_message(session_id, "assistant", ev_dict["text"])
                            first_ai_text_saved = True
                        else:
                            last_ai_text = ev_dict["text"]
                    elif ev_dict.get("event") == "task_done" and last_ai_text:
                        await chat_store.save_message(session_id, "assistant", last_ai_text)
                    await adapter.send_event(ev_dict)
            except GatewayError as exc:
                # V6: single dispatch over the unified error tree. Keeping the
                # match in one place (vs the old 3 separate except clauses)
                # means new WS codes can be added by extending one dict, not
                # by adding another except branch that might drift.
                log.warning("[MyClaw Chat] GatewayError: %r", exc)
                if not ws.closed:
                    await ws.send_json(_gateway_error_payload(exc, run_id, lang))
            except Exception as exc:
                log.exception("[MyClaw Chat] Runner error: %s", exc)
                if not ws.closed:
                    code = ERROR_NO_PROVIDERS if not req.app["providers"] else ERROR_FAILED
                    await ws.send_json({
                        "type": "error", "run_id": run_id,
                        "code": code,
                        "message": ai_error_message(code, lang),
                    })
            finally:
                # P2-NEW: Only clear the slot if *we* are still the active runner.
                # After abort-then-replace, a new runner may already be assigned; clearing
                # unconditionally would null it out and break confirm/abort routing.
                if current_runner is runner:
                    current_runner = None

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        data = {"message": msg.data}

                    # Handle abort — wait for runner to finish, then ack.
                    # P2-NEW: Await cancellation fully before returning ack, so the next
                    # message doesn't race with an old task's finally block.
                    if data.get("type") == "abort":
                        abort_run_id = data.get("run_id") or current_run_id
                        if current_runner:
                            current_runner.abort()
                            if runner_task and not runner_task.done():
                                try:
                                    await asyncio.wait_for(runner_task, timeout=5.0)
                                except asyncio.TimeoutError:
                                    runner_task.cancel()
                                    try:
                                        await runner_task
                                    except (asyncio.CancelledError, Exception):
                                        pass
                                except asyncio.CancelledError:
                                    pass
                            current_runner = None
                            runner_task = None
                        await _release_hid("abort")
                        if not ws.closed:
                            await ws.send_json({"type": "abort_ack", "run_id": abort_run_id})
                        continue

                    # Abort-then-replace: if runner is active, abort it and start new one.
                    # P2-NEW: Await cancellation to completion so the old task's finally block
                    # runs *before* we install the new runner — otherwise the old finally
                    # could race with the new runner and null its slot.
                    if current_runner:
                        current_runner.abort()
                        if runner_task and not runner_task.done():
                            try:
                                await asyncio.wait_for(runner_task, timeout=5.0)
                            except asyncio.TimeoutError:
                                runner_task.cancel()
                                try:
                                    await runner_task
                                except (asyncio.CancelledError, Exception):
                                    pass
                            except asyncio.CancelledError:
                                pass
                        current_runner = None
                        runner_task = None
                        await _release_hid("replace")

                    # Extract user message
                    instruction = (
                        data.get("message")
                        or data.get("content")
                        or data.get("instruction")
                        or ""
                    ).strip()
                    if not instruction:
                        continue

                    mode = data.get("mode", "suggest")
                    lang = data.get("lang", "zh")

                    # Use client-provided run_id; fall back to server-generated if absent
                    current_run_id = data.get("run_id") or uuid.uuid4().hex

                    # Pre-check: downgrade auto→suggest. Two distinct gates with
                    # entitlement taking priority over local model capability —
                    # an unsubscribed device wouldn't be able to auto even with
                    # a perfect tool-capable model (no MyClaw signing seat), so
                    # the toast must point at the real blocker (subscription),
                    # not mislead the user into shopping for a different model.
                    if mode == "auto":
                        _ent = req.app["cfg"].subscription.entitlement_state
                        if _ent != "paid":
                            mode = "suggest"
                            _gate_msgs = {
                                "zh": "自动模式需要 Standard 或 Pro 订阅。当前设备未订阅，已切换到建议模式。请前往 kvmind.com 升级。",
                                "ja": "自動モードには Standard または Pro プランが必要です。本デバイスは未契約のため提案モードに切り替えました。kvmind.com からアップグレードしてください。",
                                "en": "Auto mode requires a Standard or Pro subscription. This device is not subscribed — switched to suggest mode. Upgrade at kvmind.com.",
                            }
                            log.info("[MyClaw Chat] auto→suggest gate: entitlement=%s lang=%s", _ent, lang)
                            await ws.send_json({
                                "type": "notice",
                                "run_id": current_run_id,
                                "code": "auto_downgraded_no_subscription",
                                "severity": "warn",
                                "message": _gate_msgs.get(lang, _gate_msgs["en"]),
                            })
                        elif not req.app["cfg"].ai.supports_tools:
                            mode = "suggest"
                            _gate_msgs = {
                                "zh": "当前 AI 模型不支持工具调用，已自动切换到建议模式。请在 MyClaw 设置中选择支持 Function Calling 的模型。",
                                "ja": "現在の AI モデルはツール呼び出しに対応していないため、提案モードに切り替えました。MyClaw 設定で Function Calling 対応モデルを選択してください。",
                                "en": "Current AI model does not support tool calling — switched to suggest mode. Pick a tool-capable model in MyClaw Settings.",
                            }
                            log.info("[MyClaw Chat] auto→suggest gate: supports_tools=false lang=%s", lang)
                            await ws.send_json({
                                "type": "notice",
                                "run_id": current_run_id,
                                "code": "auto_downgraded_no_tool_support",
                                "severity": "warn",
                                "message": _gate_msgs.get(lang, _gate_msgs["en"]),
                            })

                    log.info("[MyClaw Chat] mode=%s instruction=%s", mode, instruction[:60])

                    # Persist user message
                    await chat_store.save_message(session_id, "user", instruction)

                    # Build structured context (Runner handles merging)
                    recent_msgs = await chat_store.get_recent_messages(session_id, limit=10)
                    context = [
                        {"role": m["role"], "content": m["content"][:200]}
                        for m in recent_msgs
                        if m["content"] != instruction
                        and not (m["role"] == "assistant" and is_tool_noise(m["content"]))
                    ][-6:]

                    # Get kvmind from app at runtime (ai_config_save may rebuild it)
                    kvmind = req.app["kvmind"]

                    # Pre-check: no AI providers configured
                    if not req.app["providers"]:
                        await ws.send_json({
                            "type": "error", "run_id": current_run_id,
                            "code": ERROR_NO_PROVIDERS,
                            "message": ai_error_message(ERROR_NO_PROVIDERS, lang),
                        })
                        continue

                    # Internal tools (non-KVM, handled by Runner directly)
                    _internal = {}
                    _task_fn = req.app.get("task_create_fn")
                    if _task_fn:
                        _internal["create_task"] = _task_fn

                    # Start Runner as background task (WS loop stays responsive for confirm/abort)
                    current_runner = Runner(
                        kvm=kvm,
                        ai_client=kvmind,
                        audit=audit,
                        mode=mode,
                        lang=lang,
                        gateway=gateway,
                        trigger="manual",
                        internal_tools=_internal,
                    )
                    runner_task = asyncio.create_task(_run_runner(current_runner, instruction, current_run_id, lang, context))

                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            if current_runner:
                current_runner.abort()
            if runner_task and not runner_task.done():
                runner_task.cancel()
                try:
                    await asyncio.wait_for(runner_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
            await _release_hid("disconnect")
            log.info("[MyClaw Chat] Session %s disconnected", session_id)
        return ws

    # ── Route registration ──────────────────────────────────────────────────

    app.router.add_get("/ws/chat", ws_chat)
    app.router.add_get("/ws/agent", ws_agent)
