"""
Subscription Binder — handles subscription key activation via kdcms backend.

Extracted from ai_config handler. Manages the network call to bind a
subscription key to a device, including tunnel token storage.
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from .config import save_config
from .uid import get_uid

log = logging.getLogger(__name__)


async def bind_subscription_key(cfg, sub_key: str) -> dict:
    """Bind a subscription key to this device via kdcms backend.

    Returns dict with either:
      - {"ok": True, "plan": "standard", ...} on success
      - {"error": "...", "message": "...", "status": 400|500} on failure
    """
    bind_url = f"{cfg.bridge.backend_url}/api/devices/bind"
    device_uid = get_uid()

    # Read device token
    device_token = ""
    token_path = Path("/etc/kdkvm/device.token")
    try:
        if token_path.exists():
            device_token = token_path.read_text().strip()
    except OSError as e:
        log.warning("[SubscriptionBinder] Failed to read device token: %s", e)

    if not device_token:
        return {
            "error": "device_not_registered",
            "message": "Device token missing. Wait for registration or run kvmind-register.sh first.",
            "status": 400,
        }

    try:
        headers = {
            "Content-Type": "application/json",
            "X-Device-Token": device_token,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(
                bind_url,
                json={"uid": device_uid, "subscriptionKey": sub_key},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                ssl=True,
            ) as r:
                result = await r.json()
                if r.status == 200 and result.get("code") == 200:
                    data = result.get("data", {})
                    plan = data.get("planType", "standard")
                    features = data.get("features") or {}
                    is_paid = plan in ("standard", "pro")
                    is_pro = plan == "pro"
                    cfg.subscription.plan = plan
                    cfg.subscription.tunnel = bool(data.get("tunnelToken"))
                    cfg.subscription.messaging = bool(features.get("messaging", is_paid))
                    cfg.subscription.ota = bool(features.get("ota", is_paid))
                    cfg.subscription.myclaw_limit = int(features.get("myclaw_limit", -1 if is_paid else 5))
                    cfg.subscription.myclaw_daily_limit = int(features.get("myclaw_daily_limit", -1 if is_paid else 20))
                    cfg.subscription.myclaw_max_action_level = int(features.get("myclaw_max_action_level", 3 if is_pro else 2 if is_paid else 1))
                    cfg.subscription.scheduled_tasks = bool(features.get("scheduled_tasks", is_pro))

                    # Write tunnel token for cloudflared service
                    tunnel_token = data.get("tunnelToken", "")
                    if tunnel_token:
                        from .remount import remount_rw
                        tp = Path("/etc/kdkvm/tunnel.token")
                        with remount_rw(str(tp)):
                            tp.write_text(tunnel_token)
                            # P1-NEW: restrict to root-only (0600). write_text replaces the file
                            # and keeps whatever mode existed — best to chmod explicitly so a
                            # previously world-readable token isn't preserved after rewrite.
                            try:
                                tp.chmod(0o600)
                            except OSError as _chmod_err:
                                log.warning("[SubscriptionBinder] chmod 600 on tunnel.token failed: %s", _chmod_err)
                        log.info("[SubscriptionBinder] Tunnel token written")

                    save_config(cfg)
                    log.info("[SubscriptionBinder] Activated: plan=%s (config persisted)", plan)
                    return {"ok": True, "plan": plan}
                else:
                    msg = result.get("message", "Activation failed")
                    log.warning("[SubscriptionBinder] Failed: %s", msg)
                    return {"error": "activation_failed", "message": msg, "status": 400}
    except Exception as e:
        log.error("[SubscriptionBinder] Error: %s", e)
        return {"error": "activation_error", "message": str(e), "status": 500}
