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
from ..myclaw_gateway import MyClawRateLimitError, MyClawForbiddenError, MyClawOfflineError
from ..middleware import validate_session, SESSION_COOKIE
from .helpers import json_response

log = logging.getLogger("kvmind.handlers.websocket")


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
            except MyClawRateLimitError as e:
                log.warning("[MyClaw Chat] Rate limited: %s", e)
                if not ws.closed:
                    err_msg = {
                        "zh": f"MyClaw 使用已达上限（{e.usage_count}/{e.usage_limit}），{e.retry_after}秒后重试",
                        "ja": f"MyClaw 使用制限に達しました（{e.usage_count}/{e.usage_limit}）、{e.retry_after}秒後にリトライ",
                        "en": f"MyClaw rate limit reached ({e.usage_count}/{e.usage_limit}), retry in {e.retry_after}s",
                    }
                    await ws.send_json({"type": "error", "run_id": run_id, "message": err_msg.get(lang, err_msg["en"]),
                                        "retry_after": e.retry_after})
            except MyClawForbiddenError as e:
                log.warning("[MyClaw Chat] Forbidden: %s", e.code)
                if not ws.closed:
                    _forbidden = {
                        "schedule_not_allowed": {"zh": "定时任务需要 Pro 订阅", "ja": "スケジュールタスクにはProが必要です", "en": "Scheduled tasks require Pro"},
                        "subscription_expired": {"zh": "订阅已过期，请续费", "ja": "サブスクリプション期限切れ", "en": "Subscription expired"},
                        "budget_exceeded": {"zh": "本轮操作预算已用尽", "ja": "操作予算超過", "en": "Operation budget exceeded"},
                    }
                    default = {"zh": f"操作被拒绝: {e.code}", "ja": f"拒否されました: {e.code}", "en": f"Denied: {e.code}"}
                    err_msg = _forbidden.get(e.code, default)
                    await ws.send_json({"type": "error", "run_id": run_id, "message": err_msg.get(lang, err_msg["en"])})
            except MyClawOfflineError:
                log.warning("[MyClaw Chat] Cloud offline")
                if not ws.closed:
                    err_msg = {"zh": "MyClaw 服务暂时不可用", "ja": "MyClaw サービス一時利用不可", "en": "MyClaw service unavailable"}
                    await ws.send_json({"type": "error", "run_id": run_id, "message": err_msg.get(lang, err_msg["en"])})
            except Exception as exc:
                log.exception("[MyClaw Chat] Runner error: %s", exc)
                if not ws.closed:
                    providers = req.app["providers"]
                    if not providers:
                        err_msg = {"zh": "AI 未配置。请在 KVM设置 中设置 AI API Key。",
                                   "ja": "AI が未設定です。KVM設定で AI API Key を設定してください。",
                                   "en": "AI is not configured. Please set your AI API Key in KVM Settings."}
                    else:
                        err_msg = {"zh": "AI 请求失败，请稍后重试。",
                                   "ja": "AI リクエストに失敗しました。再試行してください。",
                                   "en": "AI request failed. Please try again later."}
                    await ws.send_json({"type": "error", "run_id": run_id, "message": err_msg.get(lang, err_msg["en"])})
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

                    # Handle confirmation (can arrive WHILE runner is waiting)
                    if data.get("type") == "confirm":
                        if current_runner:
                            confirm_run_id = data.get("run_id")
                            if confirm_run_id and confirm_run_id != current_run_id:
                                log.warning("[MyClaw Chat] Stale confirm ignored: got run_id=%s, current=%s",
                                            confirm_run_id, current_run_id)
                            else:
                                current_runner.resolve_confirm(bool(data.get("approved", False)))
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

                    # Pre-check: downgrade auto→suggest if model lacks tool support
                    if mode == "auto" and not req.app["cfg"].ai.supports_tools:
                        mode = "suggest"
                        _gate_msgs = {
                            "zh": "当前模型不支持工具调用，已自动切换到建议模式。",
                            "ja": "現在のモデルはツール呼び出しに対応していないため、提案モードに切り替えました。",
                            "en": "Current model does not support tool calling — switched to suggest mode.",
                        }
                        await ws.send_json({"type": "ai_text", "run_id": current_run_id, "text": _gate_msgs.get(lang, _gate_msgs["en"])})

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
                        _no_ai = {
                            "zh": "AI 未配置。请在设置页面配置 AI API Key 或绑定订阅。",
                            "ja": "AI が未設定です。設定ページで AI API Key を設定するか、サブスクリプションを紐づけてください。",
                            "en": "AI is not configured. Please set your AI API Key in Settings, or bind a subscription.",
                        }
                        await ws.send_json({"type": "error", "run_id": current_run_id, "message": _no_ai.get(lang, _no_ai["en"])})
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
