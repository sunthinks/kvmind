"""
V6 first-boot bootstrap — register the device's Ed25519 pubkey with kdcms.

Replaces the V5 two-step ``ensure_registered`` → ``ensure_bootstrapped`` dance
with a single idempotent endpoint: kdcms upserts ``devices`` and
``device_keys`` in one transaction, so kdkvm needs exactly one network call
before it can sign requests.

Idempotency contract:
  * kdcms bootstrap endpoint returns 200 for both "created" and "exists with
    matching pubkey" cases.
  * kdkvm persists ``kv.bootstrap_done = "true"`` after the first success so
    subsequent starts short-circuit without even touching the network.
  * When the user runs ``kdkvm reset``, the CLI clears ``bootstrap_done`` so
    the next startup re-registers the freshly-generated pubkey.

Failure modes:
  * Transport error (DNS / TCP / TLS) → log-and-skip. The device will retry
    on the next boot / service restart. Heartbeat + MyClaw still fail with
    ``AuthError(unknown_device_uid)`` in the meantime, which the WS dispatch
    surfaces as ``device_unbound`` — exactly the state we want the user to
    see before activation.
  * 400 / 422 from kdcms → persistent config problem (bad UID / bad pubkey).
    Log loudly; do not set ``bootstrap_done``. Retrying won't help but also
    won't make things worse.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .device_keys import ensure_keypair, pubkey_pem
from .state_db import get_state_db
from .uid import get_uid

log = logging.getLogger(__name__)

BOOTSTRAP_KV_KEY = "bootstrap_done"
BOOTSTRAP_PATH = "/api/devices/bootstrap"


async def ensure_bootstrapped(cfg) -> bool:
    """Register this device's pubkey with kdcms if not already done.

    Returns ``True`` if the device is now known-bootstrapped (either by this
    call or by a prior one), ``False`` if the attempt failed and the caller
    should treat the device as not-yet-registered.

    Callers: ``server.create_app`` startup, ``heartbeat._one_tick`` recovery
    path (when a 401 ``unknown_device_uid`` suggests kdcms dropped our row).
    """
    db = get_state_db()
    if (db.kv_get(BOOTSTRAP_KV_KEY) or "").lower() == "true":
        return True

    uid = get_uid()
    # ensure_keypair() is separately called by server startup, but we call it
    # here too so the heartbeat recovery path (which may invoke
    # ensure_bootstrapped without the startup helper) still succeeds.
    ensure_keypair()
    pem = pubkey_pem()

    url = f"{cfg.bridge.backend_url}{BOOTSTRAP_PATH}"
    payload: dict[str, Any] = {
        "uid": uid,
        "publicKey": pem,
        "algorithm": "ed25519",
    }
    body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                data=body_bytes,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=15),
                ssl=True,
            ) as r:
                if r.status == 200 or r.status == 201:
                    db.kv_set(BOOTSTRAP_KV_KEY, "true")
                    log.info("[Bootstrap] device %s registered (status=%d)", uid, r.status)
                    return True
                body = await r.text()
                log.warning("[Bootstrap] kdcms returned %d: %s", r.status, body[:300])
                return False
    except Exception as e:
        log.warning("[Bootstrap] transport error: %s", e)
        return False


def mark_bootstrap_stale() -> None:
    """Clear the ``bootstrap_done`` flag so the next call re-registers.

    Used by the heartbeat self-heal path when kdcms answers 401 with
    ``unknown_device_uid`` — that means our row got deleted on the server
    and we need to re-bootstrap before trying again. The caller should
    invoke :func:`ensure_bootstrapped` immediately after.
    """
    get_state_db().kv_delete(BOOTSTRAP_KV_KEY)
