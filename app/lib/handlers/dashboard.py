"""Dashboard stats, memory API, and static page handlers."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from aiohttp import web

from ..middleware import validate_session, SESSION_COOKIE
from ..uid import get_uid
from .helpers import json_response

log = logging.getLogger(__name__)

WEB_DIR = Path("/opt/kvmind/kdkvm/web")


def _collect_system_stats() -> tuple:
    """Blocking I/O — must run in thread."""
    import shutil
    import subprocess
    import platform

    # 1. Device info
    version_file = WEB_DIR / "version.json"
    ver = {}
    try:
        ver = json.loads(version_file.read_text())
    except Exception:
        log.warning("Cannot read %s", version_file)
    uptime_s = 0.0
    try:
        uptime_s = float(open("/proc/uptime").read().split()[0])
    except Exception:
        log.warning("Cannot read /proc/uptime")
    device = {
        "version": ver.get("version", "unknown"),
        "build": ver.get("build", ""),
        "codename": ver.get("codename", ""),
        "hostname": platform.node(),
        "uid": get_uid(),
        "uptime_hours": round(uptime_s / 3600, 1),
    }

    # 2. System health
    health: Dict[str, Any] = {}
    try:
        r = subprocess.run(["vcgencmd", "measure_temp"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            health["cpu_temp"] = r.stdout.strip().replace("temp=", "").replace("'C", "")
    except Exception:
        log.warning("Cannot read CPU temperature (vcgencmd)")
        health["cpu_temp"] = None
    try:
        mi = open("/proc/meminfo").read()
        total = int([l for l in mi.split("\n") if "MemTotal" in l][0].split()[1])
        avail = int([l for l in mi.split("\n") if "MemAvailable" in l][0].split()[1])
        health["mem_total_mb"] = round(total / 1024)
        health["mem_used_mb"] = round((total - avail) / 1024)
    except Exception:
        log.warning("Cannot read /proc/meminfo")
    try:
        du = shutil.disk_usage("/")
        health["disk_total_gb"] = round(du.total / 1e9, 1)
        health["disk_used_gb"] = round(du.used / 1e9, 1)
    except Exception:
        log.warning("Cannot read disk usage")
    return device, health


def register(app):
    audit = app["audit"]
    memory_store = app["memory_store"]

    # ── Dashboard stats ────────────────────────────────────────────────────

    async def h_dashboard_stats(req: web.Request) -> web.Response:
        """GET /api/dashboard/stats — aggregate device, health, AI usage."""
        from datetime import datetime, timezone, timedelta

        device, health = await asyncio.to_thread(_collect_system_stats)

        # 3. AI usage stats (from audit log)
        entries = audit.recent(200)
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        ai_stats = {"tasks_today": 0, "tasks_week": 0, "actions_week": 0, "errors_week": 0}
        for e in entries:
            ts_str = e.get("ts", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                log.debug("Skipping audit entry with unparseable timestamp: %s", ts_str)
                continue
            et = e.get("event_type", "")
            if et == "task_start":
                if ts >= today_start:
                    ai_stats["tasks_today"] += 1
                if ts >= week_start:
                    ai_stats["tasks_week"] += 1
            elif et == "action":
                if ts >= week_start:
                    ai_stats["actions_week"] += 1
                if e.get("data", {}).get("status") == "error" and ts >= week_start:
                    ai_stats["errors_week"] += 1

        # 4. Recent activity
        recent = audit.recent(10)

        return json_response({
            "device": device, "health": health, "ai": ai_stats, "recent": recent,
        })

    # ── Memory API ─────────────────────────────────────────────────────────

    async def h_memory_get(req: web.Request) -> web.Response:
        """GET /api/ai/memory — return memories list."""
        memories = await memory_store.recall(limit=50)
        return json_response({"count": len(memories), "memories": memories})

    async def h_memory_clear(req: web.Request) -> web.Response:
        """DELETE /api/ai/memory — clear all memories."""
        n = await memory_store.clear_all()
        log.info("[Memory] Cleared %d memories", n)
        return json_response({"status": "ok", "deleted": n})

    # ── Static pages ───────────────────────────────────────────────────────

    def _serve_page(filename: str):
        async def handler(req: web.Request) -> web.Response:
            f = WEB_DIR / filename
            return web.FileResponse(f) if f.exists() else web.Response(status=404, text=f"{filename} not found")
        return handler

    async def h_index(req: web.Request) -> web.Response:
        """GET / — serve index.html if authenticated, redirect otherwise."""
        token = req.cookies.get(SESSION_COOKIE, "")
        if not validate_session(token):
            raise web.HTTPFound("/login.html")
        return await _serve_page("index.html")(req)

    # ── Route registration ─────────────────────────────────────────────────

    app.router.add_get("/api/dashboard/stats", h_dashboard_stats)
    app.router.add_get("/api/ai/memory", h_memory_get)
    app.router.add_delete("/api/ai/memory", h_memory_clear)
    app.router.add_get("/", h_index)
    app.router.add_get("/login.html", _serve_page("login.html"))
    app.router.add_get("/setup.html", _serve_page("setup.html"))
    app.router.add_get("/change-password.html", _serve_page("change-password.html"))
    app.router.add_get("/dashboard.html", _serve_page("dashboard.html"))
