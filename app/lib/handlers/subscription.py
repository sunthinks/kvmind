"""Subscription status and sync handlers."""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from ..middleware import is_trusted_proxy
from ..config import save_config
from .helpers import json_response

log = logging.getLogger("kvmind.handlers.subscription")


def _bool_from_body(value, default: bool) -> bool:
    """Parse optional JSON bools without treating "false" as True."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def register(app: dict) -> None:
    """Register subscription-related routes on the aiohttp app."""

    cfg = app["cfg"]
    kvm = app["kvm"]
    audit = app["audit"]

    async def h_subscription(req: web.Request) -> web.Response:
        """GET /api/subscription -- read subscription status."""
        return json_response({
            "plan": cfg.subscription.plan,
            "tunnel": cfg.subscription.tunnel,
            "messaging": cfg.subscription.messaging,
            "ota": cfg.subscription.ota,
            "myclaw_limit": cfg.subscription.myclaw_limit,
            "myclaw_daily_limit": cfg.subscription.myclaw_daily_limit,
            "myclaw_max_action_level": cfg.subscription.myclaw_max_action_level,
            "scheduled_tasks": cfg.subscription.scheduled_tasks,
            "synced_at": cfg.subscription.synced_at,
        })

    async def h_subscription_sync(req: web.Request) -> web.Response:
        """POST /api/subscription/sync -- heartbeat sync."""
        if not is_trusted_proxy(req):
            return web.Response(status=403, text="Forbidden")
        body = await req.json()

        old_messaging = cfg.subscription.messaging

        # Compute new values
        new_plan = body.get("plan", cfg.subscription.plan)
        new_tunnel = _bool_from_body(body.get("tunnel"), cfg.subscription.tunnel)
        new_messaging = _bool_from_body(body.get("messaging"), cfg.subscription.messaging)
        new_ota = _bool_from_body(body.get("ota"), cfg.subscription.ota)
        new_myclaw_limit = int(body.get("myclaw_limit", cfg.subscription.myclaw_limit))
        new_myclaw_daily_limit = int(body.get("myclaw_daily_limit", cfg.subscription.myclaw_daily_limit))
        new_myclaw_max_action_level = int(body.get("myclaw_max_action_level", cfg.subscription.myclaw_max_action_level))
        new_scheduled_tasks = _bool_from_body(
            body.get("scheduled_tasks"), cfg.subscription.scheduled_tasks,
        )

        # Check if anything actually changed (skip synced_at — it changes every call)
        changed = (
            new_plan != cfg.subscription.plan
            or new_tunnel != cfg.subscription.tunnel
            or new_messaging != cfg.subscription.messaging
            or new_ota != cfg.subscription.ota
            or new_myclaw_limit != cfg.subscription.myclaw_limit
            or new_myclaw_daily_limit != cfg.subscription.myclaw_daily_limit
            or new_myclaw_max_action_level != cfg.subscription.myclaw_max_action_level
            or new_scheduled_tasks != cfg.subscription.scheduled_tasks
        )

        # Always update in-memory (including synced_at)
        cfg.subscription.plan = new_plan
        cfg.subscription.tunnel = new_tunnel
        cfg.subscription.messaging = new_messaging
        cfg.subscription.ota = new_ota
        cfg.subscription.synced_at = body.get("synced_at", cfg.subscription.synced_at)
        cfg.subscription.myclaw_limit = new_myclaw_limit
        cfg.subscription.myclaw_daily_limit = new_myclaw_daily_limit
        cfg.subscription.myclaw_max_action_level = new_myclaw_max_action_level
        cfg.subscription.scheduled_tasks = new_scheduled_tasks

        # Only write to disk (remount rw/ro) when values actually changed
        if changed:
            try:
                save_config(cfg)
            except Exception as e:
                log.warning("[Subscription] Failed to save config: %s", e)

        new_messaging = cfg.subscription.messaging

        # Telegram dynamic start/stop
        if old_messaging and not new_messaging:
            # Subscription expired -> stop Bot
            task = req.app.get("telegram_task")
            if task:
                task.cancel()
                req.app.pop("telegram_task", None)
                log.info("[Subscription] Telegram stopped (messaging disabled)")
        elif not old_messaging and new_messaging and cfg.telegram.bot_token:
            # Subscription activated -> auto-start Bot (if token configured)
            kvmind = app["kvmind"]
            from ..telegram_bot import TelegramBot
            gateway = app.get("gateway")
            tg_bot = TelegramBot(
                token=cfg.telegram.bot_token, kvm=kvm, kvmind=kvmind,
                audit=audit, allowed_chats=cfg.telegram.allowed_chats or None,
                gateway=gateway,
            )
            req.app["telegram_task"] = asyncio.create_task(tg_bot.start())
            log.info("[Subscription] Telegram auto-started (messaging enabled)")

        log.info("[Subscription] Synced: plan=%s tunnel=%s messaging=%s ota=%s",
                 cfg.subscription.plan, cfg.subscription.tunnel,
                 cfg.subscription.messaging, cfg.subscription.ota)
        return json_response({"ok": True})

    # ── R4-C2: GDPR chat wipe (pull model) ────────────────────────────────────
    #
    # 由 kvmind-heartbeat.sh 在收到云端心跳的 customerCleared=true 后调用。
    # 只接受 trusted proxy (127.0.0.1) 来源，防止租户侧 Web 恶意调用。
    #
    # 返回体: {"ok": true, "deleted": <int>}  — 成功，擦除了多少条消息
    #         {"ok": false, "error": "..."}   — 失败，由 shell 转报给云端 ACK
    # ────────────────────────────────────────────────────────────────────────
    async def h_internal_chat_wipe(req: web.Request) -> web.Response:
        if not is_trusted_proxy(req):
            return web.Response(status=403, text="Forbidden")

        try:
            body = await req.json()
        except Exception:
            return json_response({"ok": False, "error": "invalid json body"}, status=400)

        deletion_request_id = body.get("deletionRequestId")
        if deletion_request_id is None:
            return json_response({"ok": False, "error": "deletionRequestId is required"}, status=400)

        chat_store = req.app.get("chat_store")
        if chat_store is None:
            return json_response({"ok": False, "error": "chat_store not initialized"}, status=500)

        try:
            # 只用 deletion_request_id 作审计 tag — chat_store 按整机全量擦除。
            deleted = await chat_store.wipe_for_uid(
                customer_uid=f"deletion_request_{deletion_request_id}"
            )
        except Exception as e:
            log.error("[ChatWipe] wipe_for_uid failed: %s", e, exc_info=True)
            return json_response(
                {"ok": False, "error": f"chat_store wipe failed: {e!s}"[:300]},
                status=500,
            )

        log.info("[ChatWipe] Wiped %d messages (deletion_request_id=%s)",
                 deleted, deletion_request_id)
        return json_response({"ok": True, "deleted": deleted})

    # ── Route registration ──────────────────────────────────────────────────

    app.router.add_get("/api/subscription", h_subscription)
    app.router.add_post("/api/subscription/sync", h_subscription_sync)
    app.router.add_post("/api/internal/chat-wipe", h_internal_chat_wipe)
