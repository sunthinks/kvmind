"""
V6 gateway error taxonomy — single source of truth for kdkvm ↔ kdcms failure shapes.

Before V6 the device had three parallel error classes with overlapping semantics
(``MyClawOfflineError`` meant "network down", "token revoked", and "clock drift"
all at once). The websocket dispatcher had to if-ladder through them to pick a
WS error code, and the mapping was implicit — editing one branch without the
others silently drifted the UX.

This module unifies failures under a ``GatewayError`` base with four concrete
subclasses. Each subclass carries the fields the websocket dispatcher needs to
emit the right WS code + CTA without inspecting the message string:

  * ``NetworkError(reason)`` — transport failure, clock skew, or 5xx.
    ``reason`` ∈ {``unreachable``, ``server_error``, ``clock_skew``}.
  * ``AuthError(reason)`` — kdcms rejected the device's Ed25519 signature.
    ``reason`` ∈ {``invalid_signature``, ``unknown_device_uid``, ``replay``,
    ``signature_expired``, ``unsupported_sig_version``}.
  * ``QuotaError(retry_after, usage_count, usage_limit)`` — HTTP 429 / rate
    limit tier exhausted.
  * ``PolicyError(code)`` — HTTP 403, ``code`` carries the server-side reason
    (``schedule_not_allowed``, ``budget_exceeded``, ...).

The plan's HTTP → exception mapping lives in :mod:`myclaw_gateway` (request
path) and :mod:`heartbeat` (heartbeat path). This module is deliberately free
of transport concerns so tests can construct any shape directly.
"""
from __future__ import annotations


class GatewayError(Exception):
    """Base class for every kdcms-side gateway failure.

    Handlers that do not care about the reason (e.g. audit logging) can catch
    ``GatewayError`` and get the human-readable message via ``str(exc)``.
    Handlers that need to pick a WS error code or CTA should catch the
    concrete subclass instead.
    """


class NetworkError(GatewayError):
    """Transport / plumbing failure — device will retry next tick.

    Three distinct reasons collapse into one exception shape because the UX
    is identical ("MyClaw offline"), but the ``reason`` field lets the WS
    layer pick a more specific user-facing message when available:

      * ``unreachable`` — DNS / TCP / TLS couldn't complete. True offline.
      * ``server_error`` — kdcms answered with 5xx. The device reached the
        server but the server failed internally — operator-actionable on
        our side, not the user's.
      * ``clock_skew`` — kdcms returned 401 with ``signature_expired``. The
        device NTP drifted past the 300s window and the user needs to fix
        it (check time, check internet NTP reachability).
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or f"network error: {reason}")


class AuthError(GatewayError):
    """kdcms rejected our signature — device is no longer trusted.

    This maps 1:1 to the ``X-Device-Sig-Error`` header kdcms emits from
    :class:`DeviceSigFilter`. Seeing any of these on a previously-working
    device means either:

      * the server deleted our device_keys row (user hit "Revoke" on
        kvmind.com) — ``unknown_device_uid``;
      * the signature bits are malformed — ``invalid_signature`` (typically
        a kdkvm bug, not an attack);
      * the nonce was already consumed — ``replay`` (duplicate delivery,
        or something captured and replayed our packet);
      * ``signature_expired`` is technically auth but the UX is clock-skew
        advisory, so :mod:`myclaw_gateway` and :mod:`heartbeat` re-raise
        it as ``NetworkError(reason='clock_skew')`` before it reaches the
        WS layer.

    The WS layer treats ``invalid_signature`` / ``unknown_device_uid`` /
    ``replay`` uniformly as ``device_unbound`` with the same CTA (prompt
    re-activation).
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or f"auth error: {reason}")


class QuotaError(GatewayError):
    """HTTP 429 — usage tier exhausted.

    Fields mirror the kdcms rate-limit body so the WS layer can show
    "X of Y used, retry in Zs" without a second API round-trip.
    """

    __slots__ = ("retry_after", "usage_count", "usage_limit")

    def __init__(self, retry_after: int = 0, usage_count: int = 0,
                 usage_limit: int = 0, message: str | None = None) -> None:
        self.retry_after = int(retry_after or 0)
        self.usage_count = int(usage_count or 0)
        self.usage_limit = int(usage_limit or 0)
        super().__init__(message or f"quota exhausted (retry after {self.retry_after}s)")


class PolicyError(GatewayError):
    """HTTP 403 with a server-defined policy code.

    ``code`` is the kdcms policy slug (``schedule_not_allowed`` /
    ``budget_exceeded`` / ...). The WS layer prefixes it with
    ``myclaw_forbidden_`` to form the UX code the frontend dispatches on.
    """

    __slots__ = ("code",)

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code or "forbidden"
        super().__init__(message or f"policy denied: {self.code}")
