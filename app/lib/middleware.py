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
    "/api/setup/complete",
    "/api/subscription/sync",   # heartbeat timer (direct to bridge, blocked at Nginx)
    "/api/internal/chat-wipe",  # R4-C2 GDPR chat wipe (heartbeat shell → bridge, Nginx-blocked)
    "/api/wifi/scan",           # needed by setup.html pre-auth
    "/api/wifi/status",         # needed by setup.html pre-auth
    "/api/wifi/connect",        # needed by setup.html pre-auth
    "/api/wifi/disconnect",     # needed by setup.html pre-auth
    "/login.html",
    "/setup.html",
    "/change-password.html",
}

# Paths only exempt from auth during first-boot (before password changed).
# Currently empty — kept for future use if we need first-boot-only endpoints.
SETUP_ONLY_NO_AUTH_PATHS: set[str] = set()

# Trusted proxy IPs — loaded from config at startup
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

@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Session-based authentication middleware."""
    path = request.path
    if not _needs_auth(path):
        return await handler(request)

    token = request.cookies.get(SESSION_COOKIE, "")
    if validate_session(token):
        return await handler(request)

    if path.startswith("/api/") or path.startswith("/ws/"):
        return web.Response(status=401, text="Unauthorized")

    raise web.HTTPFound("/login.html")


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
