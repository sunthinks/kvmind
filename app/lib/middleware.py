"""
Session management, auth middleware, and WebSocket hub.

Extracted from server.py — these are module-level utilities with no
dependency on the aiohttp app dict.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Set

from aiohttp import web

log = logging.getLogger(__name__)

# ── Session management ─────────────────────────────────────────────────────────

SESSION_COOKIE = "kvmind_session"
SESSION_TTL = 86400       # 24 hours (default)
SESSION_TTL_LONG = 604800  # 7 days ("remember device")
SESSION_MAX = 100         # Max concurrent sessions; oldest evicted when exceeded

# In-memory session store: {token: {"created": timestamp, "user": str, "ttl": int}}
_sessions: Dict[str, Dict[str, Any]] = {}


def create_session(user: str = "user", remember: bool = False) -> tuple[str, int]:
    """Create a new session. Returns (token, ttl_seconds)."""
    # Evict expired sessions first, then cap at SESSION_MAX
    if len(_sessions) >= SESSION_MAX:
        cleanup_sessions()
    if len(_sessions) >= SESSION_MAX:
        # Still over limit — evict oldest sessions
        sorted_tokens = sorted(_sessions, key=lambda k: _sessions[k]["created"])
        for old_token in sorted_tokens[: len(_sessions) - SESSION_MAX + 1]:
            _sessions.pop(old_token, None)
    token = uuid.uuid4().hex
    ttl = SESSION_TTL_LONG if remember else SESSION_TTL
    _sessions[token] = {"created": time.time(), "user": user, "ttl": ttl}
    return token, ttl


def validate_session(token: str) -> bool:
    """Check if a session token is valid and not expired."""
    sess = _sessions.get(token)
    if not sess:
        return False
    ttl = sess.get("ttl", SESSION_TTL)
    if time.time() - sess["created"] > ttl:
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token: str) -> None:
    """Remove a session."""
    _sessions.pop(token, None)


def cleanup_sessions() -> None:
    """Remove expired sessions."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["created"] > v.get("ttl", SESSION_TTL)]
    for k in expired:
        del _sessions[k]


async def _session_cleaner_loop() -> None:
    """Background task: clean expired sessions every hour."""
    while True:
        await asyncio.sleep(3600)
        before = len(_sessions)
        cleanup_sessions()
        after = len(_sessions)
        if before != after:
            log.info("[Session] Cleaned %d expired sessions (%d remaining)", before - after, after)


def start_session_cleaner(app) -> None:
    """Start the periodic session cleanup background task on app startup."""
    async def _on_startup(app) -> None:
        app["_session_cleaner"] = asyncio.create_task(_session_cleaner_loop())
        log.info("[Session] Periodic cleaner started (interval=1h, max=%d)", SESSION_MAX)

    async def _on_cleanup(app) -> None:
        task = app.get("_session_cleaner")
        if task:
            task.cancel()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)


# ── Paths that skip auth ───────────────────────────────────────────────────────

NO_AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/check",
    # /api/auth/change-password intentionally NOT listed here — requires auth
    # via middleware (defense-in-depth). Handler has its own session check too.
    "/api/device/uid",
    "/api/status",              # read-only probe, needed by setup.html test step
    "/api/setup/complete",
    "/api/subscription/sync",   # heartbeat timer (direct to bridge, blocked at Nginx)
    "/api/wifi/scan",           # read-only scan — safe pre-auth
    "/api/wifi/status",         # read-only status — safe pre-auth
    "/login.html",
    "/setup.html",
    "/change-password.html",
}

# Paths only exempt from auth during first-boot (before password changed).
# audit-r4 R4-SEC-01: wifi mutation + AI credential endpoints must require
# session once device is activated; otherwise anyone reaching port 8081 (LAN
# or via tunnel) could overwrite AI provider API key or WiFi credentials.
SETUP_ONLY_NO_AUTH_PATHS: set[str] = {
    "/api/wifi/connect",        # mutates network config — setup.html only
    "/api/wifi/disconnect",     # mutates network config — setup.html only
    "/api/ai/config",           # reads/writes AI provider + api_key — setup.html only
    "/api/ai/test",             # forwards api_key to base_url — setup.html only
    "/api/ai/models",           # forwards api_key to base_url — setup.html only
}

# Trusted proxy IPs. Hard-coded to loopback because every legitimate caller of
# `/api/subscription/sync` (and other endpoints that gate on is_trusted_proxy)
# is the device-local nginx running on the same box. The reverse-proxy → app
# hop never crosses the LAN. If a future deployment puts nginx on a sidecar
# container or a separate host, change this to load from `/etc/kdkvm/config.yaml`
# (set CONFIG.TRUSTED_PROXIES) — that's what the older comment promised.
# (TD-07 — 2026-04-26: aligned the comment with the actual implementation.)
TRUSTED_PROXIES: set[str] = {"127.0.0.1"}


def _needs_auth(path: str) -> bool:
    """Determine if a request path requires authentication."""
    if path in NO_AUTH_PATHS:
        return False
    if path in SETUP_ONLY_NO_AUTH_PATHS:
        # Lazy import avoids circular dependency risk.
        from .auth_manager import needs_password_change
        if needs_password_change():
            return False
    # No wildcard prefix match — all exempt paths must be listed explicitly
    # in NO_AUTH_PATHS to prevent accidental exposure of new routes.
    return True


def is_trusted_proxy(request: web.Request) -> bool:
    """Check if request comes from a trusted gateway proxy."""
    peername = request.transport.get_extra_info("peername")
    if peername:
        remote_ip = peername[0]
        if remote_ip in TRUSTED_PROXIES:
            return True
    return False


# ── Auth middleware ─────────────────────────────────────────────────────────────

# TD-24 (2026-04-26) — security response headers for the device-local web UI.
# These are intentionally conservative because the UI is LAN-only:
#   * X-Frame-Options DENY: device console must never render inside an iframe
#     (clickjacking would let an attacker LAN-side wrap a phishing page that
#     proxies clicks to /api/binding/release etc.)
#   * Content-Security-Policy default-src 'self' + the inline allowances the
#     existing pages need (kvmind.css uses inline <style>; activate.html builds
#     DOM with template strings — once TD-23 lands those become DOM API and
#     'unsafe-inline' on script-src can be tightened).
#   * Referrer-Policy same-origin: don't leak local URLs (which can carry
#     session-tied query params during binding flows) to upstream pages.
#   * X-Content-Type-Options nosniff: standard hardening.
# We do NOT set HSTS — kdkvm serves HTTPS via the Cloudflare tunnel, but
# accessing the device on the LAN is HTTP-only and HSTS would lock users out.
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self' wss: ws:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Session-based authentication middleware.

    Sets ``request["authenticated"]`` so handlers can distinguish a genuine
    logged-in caller from an unauthenticated one that is merely hitting an
    exempt path. Handlers that forward saved secrets (e.g. ``/api/ai/models``
    reading a stored API key) must refuse to do so when the flag is False.
    """
    path = request.path
    token = request.cookies.get(SESSION_COOKIE, "")
    session_ok = validate_session(token)

    if not _needs_auth(path):
        request["authenticated"] = session_ok
        response = await handler(request)
        _apply_security_headers(response)
        return response

    if session_ok:
        request["authenticated"] = True
        response = await handler(request)
        _apply_security_headers(response)
        return response

    if path.startswith("/api/") or path.startswith("/ws/"):
        response = web.Response(status=401, text="Unauthorized")
        _apply_security_headers(response)
        return response

    raise web.HTTPFound("/login.html")


def _apply_security_headers(response: web.StreamResponse) -> None:
    """TD-24: add defense-in-depth headers to every response.

    HTTPFound (used for the unauth → /login.html redirect) is raised, not
    returned, so it bypasses this — that is intentional: a 302 with no body
    has nothing meaningful for CSP/X-Frame-Options to protect.

    Skipping when a header is already set lets handlers override on a case
    basis (e.g. a future static asset endpoint that needs a longer CSP).
    """
    for name, value in _SECURITY_HEADERS.items():
        if name not in response.headers:
            response.headers[name] = value


# ── WebSocket client registry ──────────────────────────────────────────────────


class WSHub:
    def __init__(self) -> None:
        self._clients: Set[web.WebSocketResponse] = set()

    def add(self, ws: web.WebSocketResponse) -> None:
        self._clients.add(ws)

    def remove(self, ws: web.WebSocketResponse) -> None:
        self._clients.discard(ws)

    async def broadcast(self, data: Dict[str, Any]) -> None:
        msg = json.dumps(data, ensure_ascii=False, default=str)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.discard(ws)
