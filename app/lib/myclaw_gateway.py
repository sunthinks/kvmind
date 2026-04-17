"""
MyClaw Gateway — device-side communication with kdcms for prompt/signing.

Handles:
- start_session: get prompt + policy from cloud
- sign_actions: get signed actions from cloud
- verify_signature: local Ed25519 verification
- offline fallback: analyse-only mode when cloud unreachable
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp

log = logging.getLogger(__name__)

VERIFY_KEY_PATH = Path("/etc/kdkvm/myclaw_verify.pub")

# R4-H5: Hard cutoff after which legacy signature layout (no customer_id prefix)
# is rejected by this device. MUST match the value of
# `app.myclaw.legacy-signature-deadline` in kdcms application.yml.
# Default 2026-05-15T00:00:00Z = 30-day rollout window after P1-7 shipped on
# 2026-04-15. Can be overridden via env var (useful for dev/test) — production
# devices inherit the compiled default.
_LEGACY_CUTOFF_DEFAULT = "2026-05-15T00:00:00Z"
LEGACY_SIGNATURE_CUTOFF_UTC = os.environ.get(
    "MYCLAW_LEGACY_SIGNATURE_DEADLINE", _LEGACY_CUTOFF_DEFAULT
)


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


def _legacy_cutoff() -> datetime:
    """Parse LEGACY_SIGNATURE_CUTOFF_UTC. On parse failure, default to EPOCH
    (i.e. reject every legacy payload) so a bad override fails safe rather
    than extending the transition window forever."""
    try:
        return datetime.fromisoformat(LEGACY_SIGNATURE_CUTOFF_UTC.replace("Z", "+00:00"))
    except Exception:
        log.error(
            "Failed to parse MYCLAW_LEGACY_SIGNATURE_DEADLINE=%r — defaulting to EPOCH "
            "(legacy payloads REJECTED)",
            LEGACY_SIGNATURE_CUTOFF_UTC,
        )
        return datetime.fromtimestamp(0, tz=timezone.utc)


class MyClawRateLimitError(Exception):
    def __init__(self, retry_after: int = 0, usage_count: int = 0, usage_limit: int = 0):
        self.retry_after = retry_after
        self.usage_count = usage_count
        self.usage_limit = usage_limit
        super().__init__(f"Rate limited, retry after {retry_after}s")


class MyClawForbiddenError(Exception):
    def __init__(self, code: str = ""):
        self.code = code
        super().__init__(f"Forbidden: {code}")


class MyClawOfflineError(Exception):
    pass


@dataclass
class StartResult:
    session_id: Optional[str]
    prompt: str
    policy: dict = field(default_factory=dict)


@dataclass
class SignedActions:
    actions: list[dict]
    signature: str
    timestamp: int
    nonce: str
    # P1-7: cross-tenant replay guard. Populated by new kdcms; absent on legacy deployments.
    # When present, the verifier includes customer_id at the head of the signing payload.
    customer_id: Optional[int] = None


# Action level mapping for device-side pre-check
ACTION_LEVELS = {
    "mouse_click": 1, "mouse_double": 1, "mouse_move": 1,
    "scroll": 1, "type_text": 1, "wait": 1, "done": 1,
    "key_tap": 1, "key_combo": 2,
    "power": 3,
}


class MyClawGateway:
    """Device-side gateway to kdcms MyClaw API."""

    def __init__(
        self,
        backend_url: str,
        device_uid: str,
        device_token: str,
        public_key_path: str = str(VERIFY_KEY_PATH),
    ):
        self._start_url = f"{backend_url}/api/myclaw/start"
        self._sign_url = f"{backend_url}/api/myclaw/sign"
        self._uid = device_uid
        self._token = device_token
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

    def _headers(self) -> dict:
        return {"X-Device-Token": self._token, "Content-Type": "application/json"}

    async def start_session(self, trigger: str, intent: str) -> Optional[StartResult]:
        """Call /api/myclaw/start. Returns prompt + policy from cloud.

        Raises MyClawRateLimitError, MyClawForbiddenError, MyClawOfflineError.
        """
        payload = {
            "deviceId": self._uid,
            "trigger": trigger,
            "intent": intent,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._start_url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()

                    if resp.status == 429:
                        raise MyClawRateLimitError(
                            retry_after=data.get("retryAfter", 0),
                            usage_count=data.get("usageCount", 0),
                            usage_limit=data.get("usageLimit", 0),
                        )
                    if resp.status == 403:
                        raise MyClawForbiddenError(code=data.get("code", ""))
                    if resp.status != 200:
                        raise MyClawOfflineError(f"Unexpected status {resp.status}: {data}")

                    if not data.get("allowed"):
                        code = data.get("code", "unknown")
                        if code == "rate_limited":
                            raise MyClawRateLimitError(
                                retry_after=data.get("retryAfter", 0),
                                usage_count=data.get("usageCount", 0),
                                usage_limit=data.get("usageLimit", 0),
                            )
                        raise MyClawForbiddenError(code=code)

                    return StartResult(
                        session_id=data["sessionId"],
                        prompt=data["prompt"],
                        policy=data.get("policy", {}),
                    )
        except (aiohttp.ClientError, OSError) as e:
            log.warning("kdcms unreachable for start: %s", e)
            return None

    async def sign_actions(self, session_id: str, actions: list[dict]) -> SignedActions:
        """Call /api/myclaw/sign. Returns signed actions."""
        payload = {
            "sessionId": session_id,
            "deviceId": self._uid,
            "actions": actions,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._sign_url, json=payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    code = data.get("code", "sign_error")
                    msg = data.get("message", f"Sign failed with status {resp.status}")
                    if resp.status == 400 and code == "budget_exceeded":
                        raise MyClawForbiddenError(code="budget_exceeded")
                    if resp.status == 403:
                        raise MyClawForbiddenError(code=code)
                    raise MyClawOfflineError(msg)

                # P1-7: capture customer_id if the backend sent one. Legacy backend
                # responses (or cached legacy SignResults) won't include the field —
                # verify_signature falls back to the legacy payload layout for those.
                raw_customer_id = data.get("customerId")
                customer_id: Optional[int] = None
                if raw_customer_id is not None:
                    try:
                        customer_id = int(raw_customer_id)
                    except (TypeError, ValueError):
                        log.warning("Non-integer customerId in sign response: %r", raw_customer_id)

                return SignedActions(
                    actions=data["actions"],
                    signature=data["signature"],
                    timestamp=data["timestamp"],
                    nonce=data["nonce"],
                    customer_id=customer_id,
                )

    def verify_signature(
        self,
        actions: list[dict],
        signature: str,
        device_uid: str,
        session_id: str,
        timestamp: int,
        nonce: str,
        customer_id: Optional[int] = None,
    ) -> bool:
        """Local Ed25519 signature verification.

        P1-7: the backend now includes {customer_id} at the head of the signing
        payload as a cross-tenant replay guard. To keep rolling upgrades safe, the
        verifier tries the new layout first (when {customer_id} is provided) and
        falls back to the legacy layout on failure. This gives devices on old
        firmware AND new backend/legacy backend combinations a working 30-day
        window to finish migrating; after that the caller should refuse when
        customer_id is None.

        R4-H5: Legacy fallback is disabled past LEGACY_SIGNATURE_CUTOFF_UTC.
        - Before cutoff: tries new layout first (if customer_id supplied), then
          legacy as fallback, exactly as P1-7 intended.
        - After cutoff: only the new layout is accepted. If customer_id is None,
          the signature is rejected outright — no legacy fallback, no silent
          drift. This closes the cross-tenant replay window permanently.
        """
        if self._public_key is None:
            log.warning("No verify key loaded — skipping signature check")
            return False

        import json
        from cryptography.exceptions import InvalidSignature

        # Canonicalize actions
        actions_json = json.dumps(actions, sort_keys=True, separators=(",", ":"))
        actions_hash = hashlib.sha256(actions_json.encode()).hexdigest()

        # Strip prefix
        if not signature.startswith("ed25519:"):
            return False
        sig_bytes = __import__("base64").b64decode(signature[8:])

        # R4-H5: Past the cutoff, no customer_id means no legacy fallback either
        # — reject immediately rather than accept a replay-vulnerable payload.
        now = datetime.now(timezone.utc)
        past_cutoff = now >= _legacy_cutoff()
        if past_cutoff and customer_id is None:
            log.warning(
                "Rejecting signature for session %s: customer_id is None after legacy cutoff %s",
                session_id,
                LEGACY_SIGNATURE_CUTOFF_UTC,
            )
            return False

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

        # Payload candidates, in preferred → fallback order:
        #   1. New-format (customer_id present): customer_id|device|session|hash|ts|nonce
        #   2. Legacy-format (only tried while still within the transition window).
        # The fallback costs one extra Ed25519 verify per mismatch; negligible CPU.
        payloads: list[str] = []
        if customer_id is not None:
            payloads.append(
                f"{customer_id}|{device_uid}|{session_id}|{actions_hash}|{timestamp}|{nonce}"
            )
        if not past_cutoff:
            payloads.append(f"{device_uid}|{session_id}|{actions_hash}|{timestamp}|{nonce}")

        for payload in payloads:
            try:
                self._public_key.verify(sig_bytes, payload.encode())
                # R4-M5 (part 2): Nonce uniqueness check — only after the crypto
                # verify succeeds, so a forged-signature probe doesn't pollute
                # our seen-nonce cache (which would DoS the legit client later).
                if not self._consume_nonce(session_id, nonce, now_unix):
                    log.warning(
                        "Rejecting signature for session %s nonce %s: "
                        "nonce already consumed — replay blocked",
                        session_id,
                        nonce,
                    )
                    return False
                return True
            except InvalidSignature:
                continue
        log.warning(
            "Invalid signature for session %s (tried %d payload formats, past_cutoff=%s)",
            session_id,
            len(payloads),
            past_cutoff,
        )
        return False

    def _consume_nonce(self, session_id: str, nonce: str, now_unix: int) -> bool:
        """R4-M5: Atomically record a (session, nonce) pair as consumed.

        Returns ``True`` if the nonce was previously unseen (signature accepted);
        ``False`` if it was already in the cache within the TTL window (replay
        rejected).

        Implementation notes:
        - OrderedDict + ``move_to_end`` gives LRU semantics for eviction.
        - Stale entries are purged inline on every call so the cache auto-trims
          even when traffic is sparse (no separate background janitor).
        - Bounded by NONCE_CACHE_MAX_SIZE to defend against memory-exhaustion
          attacks where a compromised client floods unique nonces.
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
                # Replay: refresh position so a burst of replay attempts doesn't
                # let the entry fall out of the cache prematurely (which would
                # silently re-open the replay window).
                self._seen_nonces.move_to_end(key)
                return False
            # Enforce the hard ceiling — evict oldest if needed before inserting.
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

