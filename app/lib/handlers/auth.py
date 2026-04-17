"""Auth handlers — login, logout, check, change-password, device UID, setup complete."""
from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from ..auth_manager import (
    verify_password, needs_password_change, change_password,
    is_initialized, init_auth, force_set_password,
)
from ..middleware import (
    SESSION_COOKIE, validate_session,
    create_session, destroy_session,
)
from ..uid import get_uid
from .helpers import json_response

log = logging.getLogger(__name__)


def register(app):
    cfg = app["cfg"]
    audit = app["audit"]

    # ── Auth handlers ───────────────────────────────────────────────────────

    async def h_auth_login(req: web.Request) -> web.Response:
        """POST /api/auth/login — unified login with password.

        Body: {"password": "...", "remember": false}
        Validates password via auth_manager (PBKDF2 hash + lockout).
        If password_changed=false, returns redirect to change-password page.
        """
        try:
            body = await req.json()
        except Exception:
            return json_response({"error": "invalid request body"}, 400)

        password_input = body.get("password", "").strip()
        remember = bool(body.get("remember", False))

        if not password_input:
            return json_response({"error": "password required"}, 400)

        if not is_initialized():
            # Auto-init with legacy config password for migration
            init_auth()

        ok, err = verify_password(password_input)
        if not ok:
            await audit.log("login_failed", {"error": err})
            return json_response({"error": err}, 403)

        # Check if forced password change is needed
        if needs_password_change():
            # Create a short-lived session for the change-password page
            token, ttl = create_session(user="pending_change", remember=False)
            resp = json_response({
                "status": "change_password",
                "message": "password change required",
                "redirect": "/change-password.html",
            })
            resp.set_cookie(SESSION_COOKIE, token, max_age=600, httponly=True, secure=True, samesite="Lax", path="/")
            return resp

        token, ttl = create_session(remember=remember)
        await audit.log("login_success", {"remember": remember})
        resp = json_response({"status": "ok", "message": "login successful"})
        resp.set_cookie(SESSION_COOKIE, token, max_age=ttl, httponly=True, secure=True, samesite="Lax", path="/")
        return resp

    async def h_auth_logout(req: web.Request) -> web.Response:
        """POST /api/auth/logout — clear session."""
        token = req.cookies.get(SESSION_COOKIE, "")
        destroy_session(token)
        resp = json_response({"status": "ok"})
        resp.del_cookie(SESSION_COOKIE, path="/")
        return resp

    async def h_auth_check(req: web.Request) -> web.Response:
        """GET /api/auth/check — check session validity (for nginx auth_request).

        NOTE: Do NOT trust proxy here. nginx auth_request always comes from
        127.0.0.1, so trusting localhost would bypass all authentication.
        Only the actual user session cookie is checked.
        """
        token = req.cookies.get(SESSION_COOKIE, "")
        if validate_session(token):
            return web.Response(status=200, text="OK")
        return web.Response(status=401, text="Unauthorized")

    async def h_auth_change_password(req: web.Request) -> web.Response:
        """POST /api/auth/change-password — change device password.

        Body: {"old_password": "...", "new_password": "..."}
        Requires a valid session (even the short-lived one from forced change).
        """
        token = req.cookies.get(SESSION_COOKIE, "")
        if not validate_session(token):
            return json_response({"error": "unauthorized"}, 401)

        try:
            body = await req.json()
        except Exception:
            return json_response({"error": "invalid request body"}, 400)

        old_pw = body.get("old_password", "").strip()
        new_pw = body.get("new_password", "").strip()
        remember = bool(body.get("remember", False))

        if not old_pw or not new_pw:
            return json_response({"error": "old_password and new_password required"}, 400)

        ok, err = change_password(old_pw, new_pw)
        if not ok:
            return json_response({"error": err}, 400)

        # Destroy old session, create new full session
        destroy_session(token)
        new_token, ttl = create_session(remember=remember)
        await audit.log("password_changed", {})
        resp = json_response({"status": "ok", "message": "password changed"})
        resp.set_cookie(SESSION_COOKIE, new_token, max_age=ttl, httponly=True, secure=True, samesite="Lax", path="/")
        return resp

    async def h_device_uid(req: web.Request) -> web.Response:
        """GET /api/device/uid — return device UID (no auth)."""
        return json_response({"uid": get_uid()})

    # ── Setup complete handler ────────────────────────────────────────────────

    async def h_setup_complete(req: web.Request) -> web.Response:
        """POST /api/setup/complete — activate device after initial setup.

        Called from setup.html after customer sets password.
        Calls kdcms activate API to change device status to online.
        """
        uid = get_uid()

        # Idempotent: if already activated, return success without touching
        # password or re-calling activate. setup.html is a persistent config
        # page — users may reopen it post-activation. Password is intentionally
        # NOT re-set here (that would let any LAN client overwrite the
        # credential, since this endpoint is in NO_AUTH_PATHS).
        if not needs_password_change():
            log.info("Setup complete called on already-activated device: %s (no-op)", uid)
            return json_response({
                "status": "ok",
                "activated": True,
                "activationStatus": "already_activated",
            })

        log.info("Setup complete requested for device: %s", uid)

        # Try to change password if provided
        try:
            body = await req.json()
            password = body.get("password", "").strip()
            if password:
                if not is_initialized():
                    init_auth()
                ok, err = force_set_password(password)
                if not ok:
                    return json_response({"error": err}, 400)
        except Exception as e:
            log.warning("Password handling error: %s", e)

        # Call kdcms activate API
        activate_url = f"{cfg.bridge.backend_url}/api/devices/{uid}/activate"
        # Read device token for authentication (same pattern as subscription_binder.py)
        device_token = ""
        try:
            token_path = Path("/etc/kdkvm/device.token")
            if token_path.exists():
                device_token = token_path.read_text().strip()
        except OSError:
            pass

        activation_status = "not_attempted"
        if not device_token:
            activation_status = "skipped_no_token"
            log.warning("No device token found, skipping activation")
        else:
            activate_headers = {"X-Device-Token": device_token}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(activate_url, headers=activate_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            activation_status = "success"
                            log.info("Device %s activated successfully", uid)
                        elif resp.status in (401, 403):
                            activation_status = "auth_failed"
                            text = await resp.text()
                            log.warning("Activate API auth failed (%s): %s", resp.status, text[:200])
                        else:
                            activation_status = "auth_failed"
                            text = await resp.text()
                            log.warning("Activate API returned %s: %s", resp.status, text[:200])
            except Exception as e:
                activation_status = "network_error"
                log.warning("Activate request failed: %s", e)

        return json_response({
            "status": "ok",
            "activated": activation_status == "success",
            "activationStatus": activation_status,
        })

    # ── Route registration ─────────────────────────────────────────────────

    app.router.add_post("/api/auth/login", h_auth_login)
    app.router.add_post("/api/auth/logout", h_auth_logout)
    app.router.add_get("/api/auth/check", h_auth_check)
    app.router.add_post("/api/auth/change-password", h_auth_change_password)
    app.router.add_get("/api/device/uid", h_device_uid)
    app.router.add_post("/api/setup/complete", h_setup_complete)
