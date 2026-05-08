"""
MyClaw Gateway — device-side communication with kdcms for prompt/signing.

Handles:
- start_session: get prompt + policy from cloud
- sign_actions: get signed actions from cloud
- verify_signature: local Ed25519 verification of returned signed actions
- error mapping: HTTP status → unified :mod:`lib.errors` exception tree

V6 (this revision): authentication moved from Bearer JWT (type=device) to
per-request Ed25519 signatures. Every outbound call carries five
``X-Device-*`` headers produced by :mod:`device_keys`. Response semantics
on the hot path:

  * 200 — success
  * 401 — kdcms signature rejection. Response header ``X-Device-Sig-Error``
    carries the reason (``invalid_signature`` / ``unknown_device_uid`` /
    ``replay_detected`` / ``signature_expired`` / ``unsupported_sig_version``).
    Mapped to :class:`AuthError` — except ``signature_expired``, which is
    re-raised as :class:`NetworkError(reason='clock_skew')` because the UX
    is "check your NTP" rather than "device unbound".
  * 403 — policy denial (``schedule_not_allowed`` / ``budget_exceeded`` /
    ...). Mapped to :class:`PolicyError`.
  * 429 — quota exhausted. Mapped to :class:`QuotaError`.
  * 5xx — kdcms internal failure. Mapped to :class:`NetworkError(reason='server_error')`.
  * Transport / DNS / TLS — :class:`NetworkError(reason='unreachable')`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import aiohttp

from .errors import AuthError, GatewayError, NetworkError, PolicyError, QuotaError

log = logging.getLogger(__name__)

# R4-CQ-04: module-level lazy ClientSession. start_session / sign_actions are
# hit on every MyClaw turn, so creating a fresh aiohttp session per call was
# wasting a TLS handshake and ~5ms of connector setup each time. A shared
# connector with per-host pooling amortises those costs across the full
# device-lifetime of cloud traffic. Closed via close_shared_session() from the
# runtime shutdown path.
_shared_session: Optional[aiohttp.ClientSession] = None
_shared_session_lock: Optional[asyncio.Lock] = None


async def _get_shared_session() -> aiohttp.ClientSession:
    global _shared_session, _shared_session_lock
    if _shared_session is not None and not _shared_session.closed:
        return _shared_session
    if _shared_session_lock is None:
        _shared_session_lock = asyncio.Lock()
    async with _shared_session_lock:
        if _shared_session is None or _shared_session.closed:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=8)
            _shared_session = aiohttp.ClientSession(connector=connector)
    return _shared_session


async def close_shared_session() -> None:
    global _shared_session
    if _shared_session is not None and not _shared_session.closed:
        await _shared_session.close()
    _shared_session = None

VERIFY_KEY_PATH = Path("/etc/kdkvm/myclaw_verify.pub")


# R4-M5: Anti-replay hardening for device-side verify_signature.
#
# The backend already includes {timestamp, nonce} in every signed payload
# (MyClawSigningService.sign), but prior to this change the device only
# verified the Ed25519 signature — meaning a captured SignedActions bundle
# could in theory be replayed against the device indefinitely (attacker
# gets mid-HID-access to the device, records a signed batch, replays it
# the next day to trigger the same actions). These guardrails close that
# window by making the device enforce the same freshness/uniqueness
# invariants the backend already encodes.
#
# - SIGNATURE_MAX_AGE_SECONDS: reject signatures whose timestamp is older
#   (or more than this in the future, to tolerate NTP skew) than now.
#   Matched to backend NONCE_TTL (120s) with slack for device clock drift.
# - NONCE_CACHE_TTL_SECONDS: remember seen (session, nonce) keys for at
#   least this long. Slightly longer than SIGNATURE_MAX_AGE to cover the
#   window where a signature is still "fresh" but already used.
# - NONCE_CACHE_MAX_SIZE: hard cap on the seen-nonce dict so a malicious
#   or buggy client can't explode device memory by generating signatures.
#   Eviction is LRU by insertion order (OrderedDict.move_to_end on access).
SIGNATURE_MAX_AGE_SECONDS = 300
NONCE_CACHE_TTL_SECONDS = 600
NONCE_CACHE_MAX_SIZE = 1024


@dataclass
class StartResult:
    session_id: Optional[str]
    prompt: str
    policy: dict = field(default_factory=dict)
    response_format: dict = field(default_factory=dict)


@dataclass
class SignedActions:
    actions: list[dict]
    signature: str
    timestamp: int
    nonce: str
    # Cross-tenant replay guard — always included in the signed payload.
    customer_id: int


# Action level mapping for device-side pre-check
ACTION_LEVELS = {
    "mouse_click": 1, "mouse_double": 1, "mouse_move": 1,
    "scroll": 1, "type_text": 1, "wait": 1, "done": 1,
    "key_tap": 1, "key_combo": 2,
    "power": 3,
}


def _url_path(url: str) -> str:
    """Extract the path component from a full URL for the signature.

    kdcms reads the request path via ``HttpServletRequest.getRequestURI()``
    which is the bare path (``/api/myclaw/start``, no scheme/host/query).
    The signed string must match byte-for-byte, so we strip here rather
    than trusting callers to pre-extract.
    """
    return urlsplit(url).path or "/"


def _serialize_body(payload: dict) -> bytes:
    """Canonical JSON bytes — deterministic so the signed body hash matches
    whatever kdcms's ``RawBodyCachingFilter`` sees on the wire.

    Using ``aiohttp``'s ``json=payload`` is NOT safe here: aiohttp serializes
    with its own whitespace / key ordering, which would diverge from what we
    hashed. We must serialize ourselves and send via ``data=body_bytes``.
    """
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


class MyClawGateway:
    """Device-side gateway to kdcms MyClaw API.

    V6 (this revision): every outbound request is signed in-line via
    :func:`device_keys.sign_request`. There is no Bearer token, no refresh,
    no cached session credential — the private key and the device UID *are*
    the credential, and they live in ``/etc/kdkvm/`` across reboots.

    Constructor takes ``cfg`` (not just ``backend_url``) so the signing path
    can read future config fields without a churn cycle, and ``device_uid``
    explicitly so tests can inject a fixture UID without monkey-patching
    :mod:`uid`.
    """

    def __init__(
        self,
        cfg,
        device_uid: str,
        public_key_path: str = str(VERIFY_KEY_PATH),
    ):
        backend_url = cfg.bridge.backend_url
        self._cfg = cfg
        self._backend_url = backend_url
        self._start_url = f"{backend_url}/api/myclaw/start"
        self._sign_url = f"{backend_url}/api/myclaw/sign"
        self._uid = device_uid
        self._public_key = None
        self._public_key_path = public_key_path
        self._load_public_key()
        # R4-M5: bounded LRU of seen (session_id, nonce) keys. OrderedDict so we
        # can evict oldest entries in O(1) when the cache is full. The lock is
        # needed because verify_signature may run from the HID executor thread
        # while a parallel sign_actions callback is still unwinding.
        self._seen_nonces: "OrderedDict[str, float]" = OrderedDict()
        self._seen_nonces_lock = threading.Lock()

    @property
    def device_uid(self) -> str:
        return self._uid

    def _load_public_key(self):
        try:
            p = Path(self._public_key_path)
            if p.exists():
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                pem = p.read_bytes()
                self._public_key = load_pem_public_key(pem)
                log.info("MyClaw verify key loaded from %s", self._public_key_path)
            else:
                log.warning("MyClaw verify key not found at %s", self._public_key_path)
        except Exception as e:
            log.error("Failed to load MyClaw verify key: %s", e)

    def _sign_headers(self, method: str, path: str, body_bytes: bytes) -> dict[str, str]:
        """Produce the five X-Device-* headers for a signed request.

        Loads the signing key lazily so kdkvm unit tests that construct a
        gateway without booting the signing path don't force a filesystem
        open on the import graph. The `Content-Type` is set by the caller
        once so every request uses identical bytes as the hashed body.
        """
        from .device_keys import load_signing_key, sign_request

        sk = load_signing_key()
        return sign_request(sk, self._uid, method, path, body_bytes)

    async def start_session(self, trigger: str, intent: str) -> Optional[StartResult]:
        """Call /api/myclaw/start. Returns prompt + policy from cloud.

        Returns ``None`` on transport failure so callers can drop into the
        offline-only path. Every other non-2xx surfaces as a typed
        :class:`GatewayError` subclass so the WS dispatch can pick a
        specific UX code.
        """
        payload = {
            "deviceId": self._uid,
            "trigger": trigger,
            "intent": intent,
        }
        body_bytes = _serialize_body(payload)
        path = _url_path(self._start_url)
        headers = self._sign_headers("POST", path, body_bytes)
        headers["Content-Type"] = "application/json"
        try:
            session = await _get_shared_session()
            async with session.post(
                self._start_url, data=body_bytes, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data: dict = {}
                try:
                    data = await resp.json()
                except Exception:
                    # Non-JSON error body — fall through with empty dict so
                    # the status-based branches still do the right thing.
                    data = {}

                _raise_for_status(resp, data)

                if not data.get("allowed"):
                    code = data.get("code", "unknown")
                    if code == "rate_limited":
                        raise QuotaError(
                            retry_after=data.get("retryAfter", 0),
                            usage_count=data.get("usageCount", 0),
                            usage_limit=data.get("usageLimit", 0),
                        )
                    raise PolicyError(code=code)

                return StartResult(
                    session_id=data["sessionId"],
                    prompt=data["prompt"],
                    policy=data.get("policy", {}),
                    response_format=data.get("responseFormat", {}) or {},
                )
        except GatewayError:
            # Typed failures bubble up so the WS dispatch can pick a CTA.
            raise
        except (aiohttp.ClientError, OSError) as e:
            log.warning("kdcms unreachable for start: %s", e)
            return None

    async def sign_actions(self, session_id: str, actions: list[dict]) -> SignedActions:
        """Call /api/myclaw/sign. Returns signed actions.

        Transport failure raises :class:`NetworkError(reason='unreachable')`
        so callers only have to catch one typed shape regardless of whether
        start or sign tripped the failure.
        """
        payload = {
            "sessionId": session_id,
            "deviceId": self._uid,
            "actions": actions,
        }
        body_bytes = _serialize_body(payload)
        path = _url_path(self._sign_url)
        headers = self._sign_headers("POST", path, body_bytes)
        headers["Content-Type"] = "application/json"
        try:
            session = await _get_shared_session()
            async with session.post(
                self._sign_url, data=body_bytes, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data: dict = {}
                try:
                    data = await resp.json()
                except Exception:
                    data = {}

                _raise_for_status(resp, data)

                raw_customer_id = data.get("customerId")
                if raw_customer_id is None:
                    raise NetworkError(
                        reason="server_error",
                        message="kdcms sign response missing customerId — device/backend version mismatch",
                    )
                try:
                    customer_id = int(raw_customer_id)
                except (TypeError, ValueError) as e:
                    raise NetworkError(
                        reason="server_error",
                        message=f"kdcms sign response has non-integer customerId: {raw_customer_id!r}",
                    ) from e

                return SignedActions(
                    actions=data["actions"],
                    signature=data["signature"],
                    timestamp=data["timestamp"],
                    nonce=data["nonce"],
                    customer_id=customer_id,
                )
        except GatewayError:
            raise
        except (aiohttp.ClientError, OSError) as e:
            log.warning("kdcms unreachable for sign: %s", e)
            raise NetworkError(reason="unreachable", message=f"kdcms unreachable: {e}") from e

    def verify_signature(
        self,
        actions: list[dict],
        signature: str,
        device_uid: str,
        session_id: str,
        timestamp: int,
        nonce: str,
        customer_id: int,
    ) -> bool:
        """Local Ed25519 signature verification.

        Payload format:
            customer_id|device_uid|session_id|sha256(canonical_actions)|timestamp|nonce

        The customer_id prefix is a cross-tenant replay guard: even if an attacker
        captures a signed batch for one device, they cannot replay it against a
        device owned by a different customer.
        """
        if self._public_key is None:
            log.warning("No verify key loaded — skipping signature check")
            return False

        import json as _json
        from cryptography.exceptions import InvalidSignature

        # Canonicalize actions
        actions_json = _json.dumps(actions, sort_keys=True, separators=(",", ":"))
        actions_hash = hashlib.sha256(actions_json.encode()).hexdigest()

        # Strip prefix
        if not signature.startswith("ed25519:"):
            return False
        sig_bytes = __import__("base64").b64decode(signature[8:])

        # R4-M5 (part 1): Freshness check BEFORE the Ed25519 verify so a captured
        # batch can't be replayed once its timestamp window expires. Cryptographic
        # verify still runs after this — we return False on stale so the caller
        # treats it identically to any other verification failure (uniform error
        # semantics, no timing side channel for "was the signature correct?").
        now_unix = int(time.time())
        if abs(now_unix - int(timestamp)) > SIGNATURE_MAX_AGE_SECONDS:
            log.warning(
                "Rejecting signature for session %s: timestamp %d is %ds from now "
                "(max allowed %ds) — likely replay or severe clock skew",
                session_id,
                timestamp,
                now_unix - int(timestamp),
                SIGNATURE_MAX_AGE_SECONDS,
            )
            return False

        payload = f"{customer_id}|{device_uid}|{session_id}|{actions_hash}|{timestamp}|{nonce}"
        try:
            self._public_key.verify(sig_bytes, payload.encode())
        except InvalidSignature:
            log.warning("Invalid signature for session %s", session_id)
            return False

        # R4-M5 (part 2) — superseded 2026-04-26.
        #
        # Originally we rejected on duplicate (session, nonce) here. That
        # collided with kdcms's MyClawSigningService.cacheSignResult, which
        # legitimately returns the SAME (signature, timestamp, nonce) for
        # SIGNCACHE_TTL_SECONDS=120s when a client re-signs identical
        # (session, actionsJson) — a routine occurrence for multi-turn LLM
        # batches that emit the same tool_calls or network-retried sign
        # requests. The first verify cached the nonce; the second legitimate
        # verify saw it as "already consumed" and bounced — UI surfaced this
        # as the misleading "Invalid signature" string via executor.py.
        #
        # Authoritative anti-replay lives on the kdcms side
        # (myclaw_sign_nonces table + tryAcquireNonce). Device-side defenses
        # remaining in force above this line:
        #   1. SIGNATURE_MAX_AGE_SECONDS freshness check (rejects stale sigs)
        #   2. Ed25519 signature verify (rejects forged sigs)
        #   3. HTTPS + device-key authentication on the sign request itself
        # We still record (session, nonce) into _seen_nonces as a
        # depth-in-defense ledger so future tightening (e.g. action-payload
        # deduper) has the data structure ready, but never reject on it.
        self._consume_nonce(session_id, nonce, now_unix)
        return True

    def _consume_nonce(self, session_id: str, nonce: str, now_unix: int) -> bool:
        """Record a (session, nonce) pair into the seen-nonces ledger.

        Always returns ``True`` — kept as a bool for backward compatibility
        with prior callers and unit tests that branched on the return value.
        Replay rejection used to live here (R4-M5) but conflicted with
        kdcms's idempotent SignResult cache; see verify_signature for the
        full rationale on why the device-side reject was removed.

        Implementation notes:
        - OrderedDict + ``move_to_end`` gives LRU semantics for eviction.
        - Stale entries are purged inline on every call so the cache auto-trims
          even when traffic is sparse (no separate background janitor).
        - Bounded by NONCE_CACHE_MAX_SIZE so a malicious or buggy client can't
          explode device memory by generating signatures.
        """
        key = f"{session_id}:{nonce}"
        cutoff = now_unix - NONCE_CACHE_TTL_SECONDS
        with self._seen_nonces_lock:
            # Inline purge of expired entries. OrderedDict iterates insertion
            # order, so we can stop at the first non-expired entry.
            while self._seen_nonces:
                oldest_key, oldest_ts = next(iter(self._seen_nonces.items()))
                if oldest_ts < cutoff:
                    self._seen_nonces.popitem(last=False)
                else:
                    break
            if key in self._seen_nonces:
                # Idempotent re-sign: refresh LRU position so the entry
                # doesn't age out mid-burst. No rejection (see verify_signature).
                self._seen_nonces.move_to_end(key)
                return True
            # Enforce hard ceiling — evict oldest if needed before inserting.
            while len(self._seen_nonces) >= NONCE_CACHE_MAX_SIZE:
                self._seen_nonces.popitem(last=False)
            self._seen_nonces[key] = now_unix
            return True

    @staticmethod
    def check_action_level(actions: list[dict], max_level: int) -> Optional[str]:
        """Device-side pre-check: returns error message if any action exceeds level."""
        for action in actions:
            name = action.get("name", "")
            level = ACTION_LEVELS.get(name)
            if level is not None and level > max_level:
                return f"Action '{name}' requires level {level}, max allowed: {max_level}"
        return None


# ── response → exception mapping ─────────────────────────────────────────


def _raise_for_status(resp: aiohttp.ClientResponse, data: dict) -> None:
    """Translate a non-2xx kdcms response into the right :mod:`lib.errors` type.

    A 2xx with a legitimate body is a no-op; callers process the JSON themselves.
    This helper only runs for error statuses and is deliberately aware of the
    ``X-Device-Sig-Error`` header surfaced by :class:`DeviceSigFilter` — without
    it, the WS dispatch cannot distinguish "device revoked" from "device clock
    skewed", and the user sees the wrong CTA.
    """
    status = resp.status
    if 200 <= status < 300:
        return

    if status == 401:
        reason = resp.headers.get("X-Device-Sig-Error", "invalid_signature")
        # signature_expired is the only 401 reason that's actionable at the
        # device side (fix NTP) rather than at the kdcms side (re-link). Map
        # to NetworkError so the WS code routes to the clock-skew CTA.
        if reason == "signature_expired":
            raise NetworkError(reason="clock_skew", message="device clock drift exceeds 300s")
        raise AuthError(reason=reason)
    if status == 403:
        code = data.get("code") or data.get("error") or "forbidden"
        raise PolicyError(code=code)
    if status == 429:
        raise QuotaError(
            retry_after=data.get("retryAfter", 0),
            usage_count=data.get("usageCount", 0),
            usage_limit=data.get("usageLimit", 0),
        )
    if 500 <= status < 600:
        raise NetworkError(reason="server_error", message=f"kdcms {status}: {data}")
    # 4xx that isn't auth / policy / quota — treat as server config error.
    raise NetworkError(reason="server_error", message=f"unexpected status {status}: {data}")
