"""System handlers — WiFi, OTA updates, and audit log."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from aiohttp import web

from .helpers import json_response

WEB_DIR = Path("/opt/kvmind/kdkvm/web")


def register(app):
    wifi = app["wifi"]
    audit = app["audit"]

    # ── WiFi ───────────────────────────────────────────────────────────────

    async def h_wifi_scan(req: web.Request) -> web.Response:
        networks = await wifi.scan()
        return json_response([n.as_dict() for n in networks])

    async def h_wifi_status(req: web.Request) -> web.Response:
        st = await wifi.status()
        return json_response(st.as_dict())

    async def h_wifi_connect(req: web.Request) -> web.Response:
        body = await req.json()
        result = await wifi.connect(body["ssid"], body.get("password", ""))
        await audit.log("wifi_connect", {"ssid": body["ssid"], "success": result["success"]})
        return json_response(result)

    async def h_wifi_disconnect(req: web.Request) -> web.Response:
        result = await wifi.disconnect()
        await audit.log("wifi_disconnect", {})
        return json_response(result)

    # ── Audit log ──────────────────────────────────────────────────────────

    async def h_audit(req: web.Request) -> web.Response:
        try:
            n = min(int(req.rel_url.query.get("n", 50)), 500)
        except (ValueError, TypeError):
            n = 50
        return json_response(audit.recent(n))

    # ── OTA updates ────────────────────────────────────────────────────────

    async def h_update_status(req: web.Request) -> web.Response:
        """GET /api/update/status — read OTA update status file."""
        status_file = Path("/tmp/kvmind-update-status.json")
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text())
            except Exception:
                return json_response({"status": "unknown", "error": "corrupt status file"})

            if data.get("status") == "available":
                try:
                    ver_file = WEB_DIR / "version.json"
                    cur = json.loads(ver_file.read_text())
                    cur_build = int(cur.get("build", 0))
                    st_build = int(data.get("current_build", 0))
                    if cur_build > st_build:
                        data["status"] = "up-to-date"
                except Exception:
                    pass

            return json_response(data)
        return json_response({"status": "never_checked"})

    async def h_update_check(req: web.Request) -> web.Response:
        """POST /api/update/check — trigger manual OTA check (no install)."""
        import subprocess as sp
        updater = Path("/opt/kvmind/kdkvm/bin/kvmind-updater.sh")
        if not updater.exists():
            return json_response({"error": "updater not found"}, status=404)
        env = dict(os.environ, KVMIND_AUTO_UPDATE="0")
        sp.Popen(["bash", str(updater)], stdout=sp.DEVNULL, stderr=sp.DEVNULL,
                 env=env, start_new_session=True)
        await audit.log("update_check", {})
        return json_response({"status": "checking", "message": "Update check started"})

    async def h_update_apply(req: web.Request) -> web.Response:
        """POST /api/update/apply — trigger OTA update installation."""
        import subprocess as sp
        updater = Path("/opt/kvmind/kdkvm/bin/kvmind-updater.sh")
        if not updater.exists():
            return json_response({"error": "updater not found"}, status=404)
        sp.Popen([
            "systemd-run", "--scope", "--quiet",
            "bash", str(updater),
        ], stdout=sp.DEVNULL, stderr=sp.DEVNULL,
           env=dict(os.environ, KVMIND_AUTO_UPDATE="1"),
           start_new_session=True)
        await audit.log("update_apply", {})
        return json_response({"status": "updating", "message": "Update installation started"})

    # ── Route registration ─────────────────────────────────────────────────

    app.router.add_get("/api/wifi/scan", h_wifi_scan)
    app.router.add_get("/api/wifi/status", h_wifi_status)
    app.router.add_post("/api/wifi/connect", h_wifi_connect)
    app.router.add_post("/api/wifi/disconnect", h_wifi_disconnect)
    app.router.add_get("/api/audit/recent", h_audit)
    app.router.add_get("/api/update/status", h_update_status)
    app.router.add_post("/api/update/check", h_update_check)
    app.router.add_post("/api/update/apply", h_update_apply)
