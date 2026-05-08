"""
M3.4 (plan §13 + §16): in-process device heartbeat loop.

Replaces the legacy ``bin/kvmind-heartbeat.sh`` + ``kvmind-heartbeat.timer``
bash pair. Runs as an asyncio background task inside the kdkvm.service
main process, so:

  * there's one source of runtime state (the main process + state.db);
  * we don't fork a curl + python3 subprocess every 60 s;
  * the auth header is the V6 Ed25519 request signature (five X-Device-*
    headers) rather than the V5 Bearer JWT.

Behaviour contract:

  1. POST ``{cfg.bridge.backend_url}/api/devices/heartbeat`` with
     ``{uid, macAddress, ipAddress, hostname, firmwareVersion}``.
     All five X-Device-* signature headers attached.
  2. Apply entitlement state + feature flags + ``tunnelToken`` to
     ``cfg.subscription`` and persist via ``save_config``.
  3. If ``tunnelToken`` changed, write it to ``state.db.kv`` under
     ``tunnel_token`` and ``systemctl restart kdkvm-cloudflared``.
  4. If ``customerCleared`` + ``deletionRequestId`` set, wipe chat store
     and ACK back to ``/api/subscription/wipe-chat/ack`` (also signed).
  5. On 401 ``unknown_device_uid`` (kdcms dropped our row), clear
     ``bootstrap_done`` and re-register once; second failure raises the
     setup UI banner.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import aiohttp

from ._version import __version__ as FIRMWARE_VERSION
from .bootstrap import ensure_bootstrapped, mark_bootstrap_stale
from .config import save_config
from .device_keys import load_signing_key, sign_request
from .state_db import get_state_db
from .uid import get_uid

log = logging.getLogger("kvmind.heartbeat")


# ── device metadata gathering ──────────────────────────────────────────────


def _read_mac() -> str:
    """Return the first non-loopback MAC we can find."""
    for iface in ("eth0", "end0", "enp0s3", "wlan0"):
        p = Path(f"/sys/class/net/{iface}/address")
        if p.exists():
            try:
                mac = p.read_text().strip()
                if mac and mac != "00:00:00:00:00:00":
                    return mac
            except OSError:
                continue
    return "unknown"


def _read_ip() -> str:
    """Best-effort primary IPv4 address — empty string if none."""
    try:
        # Doesn't actually send packets; kernel picks the egress interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return ""


def _build_payload() -> dict:
    return {
        "uid": get_uid(),
        "macAddress": _read_mac(),
        "ipAddress": _read_ip(),
        "hostname": socket.gethostname(),
        "firmwareVersion": FIRMWARE_VERSION,
    }


# ── subscription payload → cfg.subscription + disk ─────────────────────────


def _bool(v, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    if v is None:
        return default
    return bool(v)


def _apply_subscription(cfg, data: dict) -> bool:
    """V1 Seat 模型：消费心跳响应的 claimState / entitlementState / features。

    Returns ``True`` if any non-timestamp field changed
    (and therefore disk persist is needed).
    """
    claim_state = data.get("claimState", cfg.subscription.claim_state)
    entitlement_state = data.get("entitlementState", cfg.subscription.entitlement_state)
    assigned_sub = data.get("assignedSubscriptionId", cfg.subscription.assigned_subscription_id)
    feat = data.get("features", {}) or {}

    is_paid = entitlement_state == "paid"
    # Pro/Standard 区别在 feature flags 内部（scheduled_tasks / myclaw_max_action_level）；
    # 设备端只需从 features map 读值，不再感知具体 plan slug。
    is_pro_features = bool(feat.get("scheduled_tasks", False))

    new = dict(
        claim_state=claim_state,
        entitlement_state=entitlement_state,
        assigned_subscription_id=assigned_sub,
        tunnel=_bool(feat.get("tunnel"), is_paid),
        messaging=_bool(feat.get("messaging"), is_paid),
        ota=_bool(feat.get("ota"), is_paid),
        scheduled_tasks=_bool(feat.get("scheduled_tasks"), is_pro_features),
        myclaw_limit=int(feat.get("myclaw_limit", -1 if is_paid else 5)),
        myclaw_daily_limit=int(feat.get("myclaw_daily_limit", -1 if is_paid else 20)),
        myclaw_max_action_level=int(feat.get(
            "myclaw_max_action_level",
            3 if is_pro_features else 2 if is_paid else 1,
        )),
    )
    changed = any(
        getattr(cfg.subscription, k) != v for k, v in new.items()
    )
    for k, v in new.items():
        setattr(cfg.subscription, k, v)
    cfg.subscription.synced_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return changed


# ── tunnel token → state.db + cloudflared restart ──────────────────────────


def _sync_tunnel_token(new_token: Optional[str]) -> bool:
    """Write the Cloudflare tunnel token to state.db. Returns True if
    changed vs. last stored value (caller restarts cloudflared)."""
    db = get_state_db()
    current = db.kv_get("tunnel_token") or ""
    new = (new_token or "").strip()
    if new == current:
        return False
    if new:
        db.kv_set("tunnel_token", new)
        log.info("[Heartbeat] tunnel_token updated (len=%d)", len(new))
    else:
        db.kv_delete("tunnel_token")
        log.info("[Heartbeat] tunnel_token cleared (plan downgraded)")
    return True


def _restart_cloudflared() -> None:
    """Nudge systemd to pick up the new token. Best-effort — failure
    (not installed, already restarting, systemd unreachable) is logged
    but not fatal: the daemon will catch up on next token rotation."""
    try:
        subprocess.run(
            ["systemctl", "restart", "kdkvm-cloudflared.service"],
            check=False,
            timeout=10,
            capture_output=True,
        )
    except Exception as e:
        log.warning("[Heartbeat] cloudflared restart failed: %s", e)


# ── signed HTTP helpers ─────────────────────────────────────────────────────


def _serialize_body(payload: dict) -> bytes:
    """Canonical JSON bytes — deterministic so kdcms sees the same body hash.

    Kept private so the whole heartbeat module uses one serializer. Using
    aiohttp's built-in ``json=`` would drift from the signed hash.
    """
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _signed_headers(method: str, url: str, body_bytes: bytes) -> dict[str, str]:
    """Return the five X-Device-* headers + Content-Type for a kdcms call."""
    sk = load_signing_key()
    path = urlsplit(url).path or "/"
    headers = sign_request(sk, get_uid(), method, path, body_bytes)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    return headers


# ── GDPR chat wipe flow ─────────────────────────────────────────────────────


async def _handle_chat_wipe(app, deletion_request_id: int, cfg) -> None:
    """Preserved from shell: wipe local chat store, ACK to cloud.

    V6: the ACK is signed (not Bearer) like every other device → kdcms call.
    """
    chat_store = app.get("chat_store")
    if chat_store is None:
        log.error("[Heartbeat][ChatWipe] chat_store missing in app")
        return

    success = False
    error_msg = ""
    try:
        deleted = await chat_store.wipe_for_uid(
            customer_uid=f"deletion_request_{deletion_request_id}",
        )
        success = True
        log.info("[Heartbeat][ChatWipe] wiped %d messages (req=%s)",
                 deleted, deletion_request_id)
    except Exception as e:
        error_msg = f"chat_store wipe failed: {e!s}"[:300]
        log.error("[Heartbeat][ChatWipe] %s", error_msg)

    # ACK cloud regardless of success so the server-side attempt_count
    # ticks correctly. Network errors here are silent — next heartbeat
    # will re-observe customerCleared and retry.
    try:
        url = f"{cfg.bridge.backend_url}/api/subscription/wipe-chat/ack"
        payload = {
            "deletionRequestId": deletion_request_id,
            "success": success,
            "errorMessage": error_msg,
        }
        body_bytes = _serialize_body(payload)
        headers = _signed_headers("POST", url, body_bytes)
        async with aiohttp.ClientSession() as s:
            await s.post(
                url,
                headers=headers,
                data=body_bytes,
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        log.warning("[Heartbeat][ChatWipe] ACK network error: %s", e)


# ── main loop ──────────────────────────────────────────────────────────────


async def _one_tick(app, cfg) -> None:
    """Run one heartbeat cycle.

    Recovery ladder on 401:
      1. First-see → mark bootstrap stale + re-run ``ensure_bootstrapped``
         so kdcms re-inserts our row if it was dropped (reinstall scenario).
      2. Still 401 → raise the setup banner (``needs_reactivation``). The
         user must re-link on kvmind.com/activate, which re-runs the
         device-authorization flow that writes ``bound_customer_id``.
    """
    url = f"{cfg.bridge.backend_url}/api/devices/heartbeat"
    payload = _build_payload()
    body_bytes = _serialize_body(payload)

    try:
        async with aiohttp.ClientSession() as s:
            status, body = await _post_signed(s, url, body_bytes)

            if status == 401 and not app.get("heartbeat_recovered_bootstrap"):
                # One-shot self-heal: drop bootstrap_done flag, re-register.
                # Flag pinned on the app dict so we don't loop re-registering
                # every tick when kdcms is stuck returning 401.
                app["heartbeat_recovered_bootstrap"] = True
                log.warning("[Heartbeat] 401 — re-registering pubkey (recovery)")
                mark_bootstrap_stale()
                if await ensure_bootstrapped(cfg):
                    # Immediately retry with the fresh registration.
                    status, body = await _post_signed(s, url, body_bytes)
            if status == 401:
                log.error(
                    "[Heartbeat] 401 unauthorized after recovery — device unbound; "
                    "raising re-activation banner"
                )
                _db = get_state_db()
                _db.kv_delete("bound_customer_email")
                _db.set_needs_reactivation(True)
                return
            if status != 200:
                log.warning("[Heartbeat] backend returned %s", status)
                return
    except Exception as e:
        log.warning("[Heartbeat] transport error: %s", e)
        return

    # A successful tick resets the recovery latch so a future 401 gets one
    # more re-bootstrap attempt instead of silently escalating.
    app.pop("heartbeat_recovered_bootstrap", None)

    if not isinstance(body, dict) or body.get("code") != 200:
        log.warning("[Heartbeat] rejected: %s", body)
        return

    data = body.get("data") or {}

    # R5-HB-01：在把 features / tunnelToken / customerCleared 等权威字段落地
    # 到本地 feature_flags.json 之前，先用 /etc/kdkvm/heartbeat_verify.pub 验签。
    # 验签失败说明 kdcms 已被入侵或 nginx 被劫持 —— 直接 return 保留旧 features，
    # 避免攻击者下发任意权益。"未带签名"分支属于兼容期，会 warn 但接受。
    try:
        from . import device_keys as _device_keys
        uid = cfg.bridge.uid if hasattr(cfg.bridge, "uid") else None
        if uid and not _device_keys.verify_heartbeat_response(uid, data):
            log.error(
                "[Heartbeat] response signature invalid — keeping previous features, "
                "this may indicate kdcms compromise or MITM"
            )
            return
    except Exception as e:
        # 验签代码本身失败时记 error 但不阻断 —— 把"功能性"放在"完整性"之上，
        # 因为心跳的 401 self-heal / GDPR wipe 等流程仍需要跑。
        log.error("[Heartbeat] signature verification path errored: %s", e)

    tunnel_token = data.get("tunnelToken") or ""
    customer_cleared = bool(data.get("customerCleared"))
    deletion_request_id = data.get("deletionRequestId")
    # V15: 已绑定时下发账户邮箱给设备 UI 展示（bound 视图）；unclaimed 时清掉。
    try:
        from . import state_db as _state_db
        _db = _state_db.get_state_db()
        cust_email = data.get("customerEmail")
        if cust_email and data.get("claimState") == "claimed":
            _db.kv_set("bound_customer_email", str(cust_email))
        elif data.get("claimState") != "claimed":
            _db.kv_delete("bound_customer_email")
    except Exception as e:
        log.warning("[Heartbeat] customer_email sync failed: %s", e)
    # V15: pendingBindingRequests 现在承载该设备所有"近期相关"binding 请求 ——
    # PENDING（双向）+ 60s 内变终态的 DEVICE_TO_ACCOUNT 请求。设备端按 direction 拆：
    #   ACCOUNT_TO_DEVICE PENDING → 缓存到 KV_PENDING_SNAPSHOT 给 incoming 视图
    #   DEVICE_TO_ACCOUNT * → 同步本地 pending_mine（被 reject/expire 时清缓存 +
    #                         写 lastResult toast，UI 立即切回 form 视图）
    try:
        from . import binding as _binding
        bindings = data.get("pendingBindingRequests")
        if isinstance(bindings, list):
            account_pending = [
                b for b in bindings
                if isinstance(b, dict)
                and (b.get("direction") == "ACCOUNT_TO_DEVICE" or b.get("initiator") == "account")
                and b.get("status") in ("PENDING_ACCOUNT_REQUEST", "pending")
            ]
            _binding.save_pending_snapshot(account_pending if account_pending else None)

            # 同步 pending_mine：找设备自己那条最新请求的当前状态
            mine = _binding.load_pending_mine()
            if mine and mine.get("id") is not None:
                my_id_str = str(mine["id"]).replace("br_", "")
                match = None
                for b in bindings:
                    if not isinstance(b, dict): continue
                    if str(b.get("id") or "") == my_id_str:
                        match = b; break
                if match is not None:
                    st = match.get("status")
                    if st in ("REJECTED", "REJECTED_BY_DEVICE"):
                        _binding.clear_pending_mine()
                        _binding.save_last_result("binding.declined", extra={"id": my_id_str})
                        _binding.disarm_fast_poll()
                    elif st == "EXPIRED":
                        _binding.clear_pending_mine()
                        _binding.save_last_result("binding.expired", extra={"id": my_id_str})
                        _binding.disarm_fast_poll()
                    elif st == "CANCELLED":
                        _binding.clear_pending_mine()
                        _binding.disarm_fast_poll()
                    elif st == "ACCEPTED":
                        # claim_state 路径会处理，但这里幂等清一下兜底
                        _binding.clear_pending_mine()
        else:
            _binding.save_pending_snapshot(None)
    except Exception as e:
        log.warning("[Heartbeat] binding snapshot save failed: %s", e)

    sub_changed = _apply_subscription(cfg, data)
    if sub_changed:
        try:
            save_config(cfg)
        except Exception as e:
            log.warning("[Heartbeat] save_config failed: %s", e)

    # V15 · 心跳响应里带 ACCOUNT_TO_DEVICE pending（账户主动发起的请求）时才 arm
    # fast-poll —— 让对端发起后的下一拍心跳秒到设备 UI；claim 完成后立即 disarm。
    # 未绑定但无 pending 的"local free"是合法静态，不强制加速心跳（=不强迫激活）。
    try:
        from . import binding as _binding
        if data.get("claimState") == "claimed":
            _binding.disarm_fast_poll()
            # 绑定完成 → 清掉本地缓存的"我发起的 6 位码"，避免 bound 视图后还残留
            _binding.clear_pending_mine()
        else:
            pending = data.get("pendingBindingRequests")
            if isinstance(pending, list) and len(pending) > 0:
                _binding.arm_fast_poll()
    except Exception as e:
        log.warning("[Heartbeat] fast-poll arm/disarm failed: %s", e)

    if _sync_tunnel_token(tunnel_token):
        _restart_cloudflared()

    if customer_cleared and deletion_request_id:
        await _handle_chat_wipe(app, int(deletion_request_id), cfg)


async def _post_signed(session: aiohttp.ClientSession, url: str, body_bytes: bytes) -> tuple[int, dict]:
    """Signed POST → (status, body-as-dict). Helper for _one_tick's recovery loop."""
    headers = _signed_headers("POST", url, body_bytes)
    async with session.post(
        url,
        headers=headers,
        data=body_bytes,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        try:
            body = await r.json(content_type=None)
        except Exception:
            body = {}
        return r.status, body if isinstance(body, dict) else {}


async def _run(app, interval_seconds: int) -> None:
    cfg = app["cfg"]
    # V15 · 绑定进行中时心跳降到 FAST_INTERVAL 秒（binding.KV_FAST_POLL_UNTIL
    # 由 request_binding / decide_binding(accept) / 心跳看到 unclaimed 续期；
    # 看到 claimState='claimed' 立即清位；或 10min TTL 自然过期）。
    # 1 秒间隔保证账户主动发起后 ≤1s 设备 UI 出 incoming 卡片；
    # accept/reject 后状态切 claimed 立即 disarm，恢复默认 interval_seconds (60s)。
    FAST_INTERVAL = 1
    log.info("[Heartbeat] loop started (interval=%ss, fast=%ss when binding in progress)",
             interval_seconds, FAST_INTERVAL)
    # Jittered initial delay so multiple devices don't stampede on boot.
    try:
        await asyncio.sleep(min(30, interval_seconds))
        while True:
            try:
                await _one_tick(app, cfg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[Heartbeat] unexpected tick failure: %s", e,
                          exc_info=True)
            # 每跳结束后动态决定下次间隔；binding 的 fast-poll flag 由
            # request/decide/cancel/tick 在 state.db 维护。
            try:
                from . import binding as _binding
                next_sleep = FAST_INTERVAL if _binding.fast_poll_active() else interval_seconds
            except Exception:
                next_sleep = interval_seconds
            await asyncio.sleep(next_sleep)
    except asyncio.CancelledError:
        log.info("[Heartbeat] loop cancelled")
        raise


def start_heartbeat(app, *, interval_seconds: int = 60) -> None:
    """Register the heartbeat as an aiohttp on_startup task.

    Intentionally runs in the same event loop as the rest of the bridge
    — no fork/exec, no per-iteration subprocess overhead."""

    async def _on_startup(app) -> None:
        app["heartbeat_task"] = asyncio.create_task(_run(app, interval_seconds))

    async def _on_shutdown(app) -> None:
        task = app.get("heartbeat_task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app.on_startup.append(_on_startup)
    app.on_shutdown.append(_on_shutdown)
