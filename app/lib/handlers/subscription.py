"""Subscription status and sync handlers (V1 Seat 模型)."""
from __future__ import annotations

import logging

from aiohttp import web

from ..middleware import is_trusted_proxy
from ..config import save_config
from ..telegram_bot import start_bot, stop_bot
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

    async def h_subscription(req: web.Request) -> web.Response:
        """GET /api/subscription — read current entitlement snapshot (V1 Seat 模型)."""
        return json_response({
            "claim_state": cfg.subscription.claim_state,
            "entitlement_state": cfg.subscription.entitlement_state,
            "assigned_subscription_id": cfg.subscription.assigned_subscription_id,
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
        """POST /api/subscription/sync — trusted-proxy heartbeat passthrough.

        V1 Seat 模型：payload 字段为 claim_state / entitlement_state / assigned_subscription_id
        外加 feature flags。老 plan / linked 字段彻底废弃。
        """
        if not is_trusted_proxy(req):
            return web.Response(status=403, text="Forbidden")
        body = await req.json()

        old_messaging = cfg.subscription.messaging
        old_scheduled = cfg.subscription.scheduled_tasks

        new_claim_state = body.get("claim_state", cfg.subscription.claim_state)
        new_entitlement_state = body.get("entitlement_state", cfg.subscription.entitlement_state)
        asid = body.get("assigned_subscription_id", cfg.subscription.assigned_subscription_id)
        new_assigned_sub = int(asid) if asid is not None else None

        new_tunnel = _bool_from_body(body.get("tunnel"), cfg.subscription.tunnel)
        new_messaging = _bool_from_body(body.get("messaging"), cfg.subscription.messaging)
        new_ota = _bool_from_body(body.get("ota"), cfg.subscription.ota)
        new_myclaw_limit = int(body.get("myclaw_limit", cfg.subscription.myclaw_limit))
        new_myclaw_daily_limit = int(body.get("myclaw_daily_limit", cfg.subscription.myclaw_daily_limit))
        new_myclaw_max_action_level = int(body.get("myclaw_max_action_level", cfg.subscription.myclaw_max_action_level))
        new_scheduled_tasks = _bool_from_body(
            body.get("scheduled_tasks"), cfg.subscription.scheduled_tasks,
        )

        changed = (
            new_claim_state != cfg.subscription.claim_state
            or new_entitlement_state != cfg.subscription.entitlement_state
            or new_assigned_sub != cfg.subscription.assigned_subscription_id
            or new_tunnel != cfg.subscription.tunnel
            or new_messaging != cfg.subscription.messaging
            or new_ota != cfg.subscription.ota
            or new_myclaw_limit != cfg.subscription.myclaw_limit
            or new_myclaw_daily_limit != cfg.subscription.myclaw_daily_limit
            or new_myclaw_max_action_level != cfg.subscription.myclaw_max_action_level
            or new_scheduled_tasks != cfg.subscription.scheduled_tasks
        )

        cfg.subscription.claim_state = new_claim_state
        cfg.subscription.entitlement_state = new_entitlement_state
        cfg.subscription.assigned_subscription_id = new_assigned_sub
        cfg.subscription.tunnel = new_tunnel
        cfg.subscription.messaging = new_messaging
        cfg.subscription.ota = new_ota
        cfg.subscription.synced_at = body.get("synced_at", cfg.subscription.synced_at)
        cfg.subscription.myclaw_limit = new_myclaw_limit
        cfg.subscription.myclaw_daily_limit = new_myclaw_daily_limit
        cfg.subscription.myclaw_max_action_level = new_myclaw_max_action_level
        cfg.subscription.scheduled_tasks = new_scheduled_tasks

        if changed:
            try:
                save_config(cfg)
            except Exception as e:
                log.warning("[Subscription] Failed to save config: %s", e)

        if old_messaging and not new_messaging:
            if stop_bot(req.app):
                log.info("[Subscription] Telegram stopped (messaging disabled)")
        elif not old_messaging and new_messaging:
            if start_bot(req.app, cfg):
                log.info("[Subscription] Telegram auto-started (messaging enabled)")

        # scheduled_tasks 翻 True/False 时同步开停 TaskScheduler，否则已运行的任务
        # 会一直跑到下次重启，等同 entitlement 被吊销但设备还在执行付费功能。
        if old_scheduled and not new_scheduled:
            sched = req.app.get("task_scheduler")
            if sched is not None:
                stopped = sched.stop_all()
                if stopped:
                    log.info("[Subscription] Stopped %d scheduled tasks (entitlement off)", stopped)
        elif not old_scheduled and new_scheduled:
            sched = req.app.get("task_scheduler")
            if sched is not None:
                started = await sched.start_all_if_entitled()
                if started:
                    log.info("[Subscription] Started %d scheduled tasks (entitlement on)", started)

        log.info(
            "[Subscription] Synced: claim=%s ent=%s sub_id=%s tunnel=%s messaging=%s ota=%s",
            cfg.subscription.claim_state,
            cfg.subscription.entitlement_state,
            cfg.subscription.assigned_subscription_id,
            cfg.subscription.tunnel,
            cfg.subscription.messaging,
            cfg.subscription.ota,
        )
        return json_response({"ok": True})

    app.router.add_get("/api/subscription", h_subscription)
    app.router.add_post("/api/subscription/sync", h_subscription_sync)
