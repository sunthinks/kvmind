"""MyClaw scheduled tasks — allowlist-only task engine with JSON persistence.

Tasks execute predefined monitoring commands (no arbitrary shell).
All execution uses create_subprocess_exec (no shell interpretation).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

from aiohttp import web

from ..remount import msd_rw
from .helpers import json_response

log = logging.getLogger(__name__)

_TASKS_FILE = "/var/lib/kvmd/msd/.kdkvm/tasks.json"
# Throttle disk persistence to reduce SD card wear (rw/ro remount cycles)
_PERSIST_INTERVAL_S = 300   # flush at most every 5 minutes
_PERSIST_EVERY_N_RUNS = 10  # or every 10 executions, whichever comes first

# ── Allowlisted task templates ────────────────────────────────────────────────
# Only these commands can be executed.  AI and API callers choose a task_type;
# the actual command is assembled from this table — never from user input.

TASK_TEMPLATES: dict[str, dict] = {
    "check_cpu": {
        "cmd": ["top", "-bn1", "-w", "120"],
        "desc": "CPU usage snapshot",
    },
    "check_memory": {
        "cmd": ["free", "-h"],
        "desc": "Memory usage",
    },
    "check_disk": {
        "cmd": ["df", "-h", "/", "/var/lib/kvmd/msd"],
        "desc": "Disk space",
    },
    "check_temp": {
        "cmd": ["vcgencmd", "measure_temp"],
        "desc": "CPU temperature",
    },
    "check_uptime": {
        "cmd": ["uptime"],
        "desc": "System uptime and load",
    },
    "check_network": {
        "cmd": ["ip", "-brief", "addr"],
        "desc": "Network interfaces",
    },
    "check_services": {
        "cmd": ["systemctl", "is-active", "kvmd", "kvmind", "nginx"],
        "desc": "Core service health",
    },
    "ping": {
        "cmd": ["ping", "-c", "1", "-W", "3"],
        "desc": "Ping a host",
        "args": ["target"],       # extra positional arg (validated)
    },
}

# Validation for the 'ping' target argument
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,253}$")


def _validate_ping_target(target: str) -> str | None:
    """Return error string if target is not a valid hostname/IP, else None."""
    if not target:
        return "target required for ping"
    if not _HOSTNAME_RE.match(target):
        return "invalid target (only hostname or IP)"
    return None


def _load_tasks() -> list[dict]:
    try:
        with open(_TASKS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_tasks(tasks: list[dict]) -> None:
    with msd_rw(_TASKS_FILE):
        os.makedirs(os.path.dirname(_TASKS_FILE), exist_ok=True)
        with open(_TASKS_FILE, "w") as f:
            json.dump(tasks, f, indent=2)


def _build_cmd(task_type: str, args: dict | None = None) -> list[str] | None:
    """Build the command list for a task_type.  Returns None if invalid."""
    tpl = TASK_TEMPLATES.get(task_type)
    if not tpl:
        return None
    cmd = list(tpl["cmd"])
    # Append validated extra arguments
    if "args" in tpl and tpl["args"]:
        args = args or {}
        for arg_name in tpl["args"]:
            val = args.get(arg_name, "")
            if task_type == "ping":
                err = _validate_ping_target(val)
                if err:
                    return None
                cmd.append(val)
    return cmd


def register(app):
    cfg = app["cfg"]

    # In-memory scheduler state: task_id → asyncio.Task
    _scheduler: dict[str, asyncio.Task] = {}
    # In-memory task definitions (updated by _run_loop, used for shutdown flush)
    _live_defs: dict[str, dict] = {}

    def _check_entitlement() -> bool:
        """Return True if subscription allows scheduled tasks."""
        return getattr(cfg.subscription, "scheduled_tasks", False)

    async def _run_loop(task_def: dict):
        """Repeating loop for a single task — executes allowlisted command."""
        schedule = task_def.get("schedule", {})
        interval_ms = schedule.get("every_ms", 60_000)
        interval_s = max(interval_ms / 1000, 10)  # floor 10s
        task_id = task_def["id"]
        task_type = task_def.get("task_type", "")
        task_args = task_def.get("args")
        persist_counter = 0
        last_persist_at = time.time()

        while True:
            await asyncio.sleep(interval_s)
            ts = int(time.time())
            task_def["last_run_at"] = ts
            task_def["run_count"] = task_def.get("run_count", 0) + 1

            cmd = _build_cmd(task_type, task_args)
            if cmd:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                    output = (stdout or b"").decode("utf-8", errors="replace").strip()
                    if proc.returncode == 0:
                        result = output[:500] or "ok"
                    else:
                        err = (stderr or b"").decode("utf-8", errors="replace").strip()
                        result = f"exit {proc.returncode}: {err[:300]}"
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                    result = "timeout (30s)"
                except Exception as exc:
                    result = f"error: {exc}"
            elif task_def.get("legacy"):
                # Legacy task with raw command — disabled at load, skip execution
                result = "legacy task (disabled)"
            else:
                result = "tick"

            task_def["last_result"] = result
            log.info("[Tasks] run: %s (%s) #%d → %s", task_def.get("name", task_id), task_id, task_def["run_count"], result[:80])

            # Throttled persistence: flush every N runs or M seconds
            persist_counter += 1
            now = time.time()
            if persist_counter >= _PERSIST_EVERY_N_RUNS or (now - last_persist_at) >= _PERSIST_INTERVAL_S:
                try:
                    tasks = _load_tasks()
                    for t in tasks:
                        if t["id"] == task_id:
                            t["last_run_at"] = ts
                            t["run_count"] = task_def["run_count"]
                            t["last_result"] = result
                            break
                    _save_tasks(tasks)
                except Exception as exc:
                    log.warning("[Tasks] failed to persist for %s: %s", task_id, exc)
                persist_counter = 0
                last_persist_at = now

    def _start_task(task_def: dict):
        """Start the scheduler loop for an enabled task."""
        tid = task_def["id"]
        if tid in _scheduler:
            _scheduler[tid].cancel()
        if task_def.get("enabled", True):
            _live_defs[tid] = task_def
            _scheduler[tid] = asyncio.ensure_future(_run_loop(task_def))

    def _stop_task(tid: str):
        t = _scheduler.pop(tid, None)
        _live_defs.pop(tid, None)
        if t:
            t.cancel()

    # ── Boot: start all enabled tasks (migrate legacy) ──
    async def _on_startup(_app):
        if not _check_entitlement():
            return
        tasks = _load_tasks()
        migrated = False
        for task_def in tasks:
            # Migrate legacy tasks: command → task_type
            if "command" in task_def and "task_type" not in task_def:
                matched = _migrate_legacy_task(task_def)
                if not matched:
                    task_def["legacy"] = True
                    task_def["enabled"] = False
                    log.warning("[Tasks] Legacy task '%s' disabled (raw command not in allowlist)", task_def.get("name"))
                migrated = True
            if task_def.get("enabled", True) and not task_def.get("legacy"):
                _start_task(task_def)
        if migrated:
            try:
                _save_tasks(tasks)
            except Exception as exc:
                log.warning("[Tasks] migration save failed: %s", exc)
        log.info("[Tasks] Loaded %d tasks from disk", len(tasks))

    app.on_startup.append(_on_startup)

    # ── Shutdown: flush in-memory tracking state to disk ──
    async def _on_cleanup(_app):
        """Persist final task tracking state on graceful shutdown."""
        if not _live_defs:
            return
        try:
            tasks = _load_tasks()
            for t in tasks:
                live = _live_defs.get(t["id"])
                if live:
                    t["last_run_at"] = live.get("last_run_at")
                    t["run_count"] = live.get("run_count", 0)
                    t["last_result"] = live.get("last_result")
            _save_tasks(tasks)
            log.info("[Tasks] Flushed %d task states on shutdown", len(_live_defs))
        except Exception as exc:
            log.warning("[Tasks] shutdown flush failed: %s", exc)
        for tid in list(_scheduler):
            _stop_task(tid)

    app.on_cleanup.append(_on_cleanup)

    # ── Handlers ──────────────────────────────────────────────────────────

    async def h_tasks_list(req: web.Request) -> web.Response:
        """GET /api/tasks — list all tasks."""
        tasks = _load_tasks()
        return json_response({"jobs": tasks, "templates": list(TASK_TEMPLATES.keys())})

    async def h_tasks_create(req: web.Request) -> web.Response:
        """POST /api/tasks — create a new task."""
        if not _check_entitlement():
            return json_response({"error": "scheduled_tasks_not_enabled"}, status=403)

        body = await req.json()
        task_type = body.get("task_type", "")
        if task_type not in TASK_TEMPLATES:
            return json_response({"error": "invalid_task_type", "allowed": list(TASK_TEMPLATES.keys())}, status=400)

        task_args = body.get("args")
        # Validate args for tasks that require them
        if task_type == "ping":
            target = (task_args or {}).get("target", "")
            err = _validate_ping_target(target)
            if err:
                return json_response({"error": err}, status=400)

        task_def = {
            "id": uuid.uuid4().hex[:12],
            "name": body.get("name", TASK_TEMPLATES[task_type]["desc"]),
            "task_type": task_type,
            "args": task_args,
            "schedule": body.get("schedule", {"kind": "every", "every_ms": 60000}),
            "enabled": body.get("enabled", True),
            "created_at": int(time.time()),
            "last_run_at": None,
            "run_count": 0,
            "last_result": None,
        }

        tasks = _load_tasks()
        tasks.append(task_def)
        _save_tasks(tasks)
        _start_task(task_def)

        return json_response({"status": "ok", "task": task_def})

    async def h_tasks_toggle(req: web.Request) -> web.Response:
        """POST /api/tasks/{id}/toggle — enable/disable a task."""
        tid = req.match_info["id"]
        tasks = _load_tasks()
        found = None
        for t in tasks:
            if t["id"] == tid:
                t["enabled"] = not t.get("enabled", True)
                found = t
                break
        if not found:
            return json_response({"error": "not_found"}, status=404)

        _save_tasks(tasks)
        if found["enabled"]:
            _start_task(found)
        else:
            _stop_task(tid)

        return json_response({"status": "ok", "enabled": found["enabled"]})

    async def h_tasks_delete(req: web.Request) -> web.Response:
        """DELETE /api/tasks/{id} — delete a task."""
        tid = req.match_info["id"]
        tasks = _load_tasks()
        new_tasks = [t for t in tasks if t["id"] != tid]
        if len(new_tasks) == len(tasks):
            return json_response({"error": "not_found"}, status=404)

        _save_tasks(new_tasks)
        _stop_task(tid)

        return json_response({"status": "ok"})

    # ── Programmatic API (for Runner / internal tools) ─────────────────────

    async def task_create_fn(body: dict) -> dict:
        """Create a task programmatically. Called by MyClaw Runner."""
        if not _check_entitlement():
            return {"error": "scheduled_tasks_not_enabled"}

        task_type = body.get("task_type", "")
        if task_type not in TASK_TEMPLATES:
            return {"error": "invalid_task_type", "allowed": list(TASK_TEMPLATES.keys())}

        task_args = body.get("args")
        if task_type == "ping":
            target = (task_args or {}).get("target", "")
            err = _validate_ping_target(target)
            if err:
                return {"error": err}

        interval_min = max(int(body.get("interval_minutes", 1)), 1)
        task_def = {
            "id": uuid.uuid4().hex[:12],
            "name": body.get("name", TASK_TEMPLATES[task_type]["desc"]),
            "task_type": task_type,
            "args": task_args,
            "schedule": {"kind": "every", "every_ms": interval_min * 60_000},
            "enabled": True,
            "created_at": int(time.time()),
            "last_run_at": None,
            "run_count": 0,
            "last_result": None,
        }
        tasks = _load_tasks()
        tasks.append(task_def)
        _save_tasks(tasks)
        _start_task(task_def)
        return {"status": "ok", "task": task_def}

    app["task_create_fn"] = task_create_fn

    # ── Route registration ─────────────────────────────────────────────────

    app.router.add_get("/api/tasks", h_tasks_list)
    app.router.add_post("/api/tasks", h_tasks_create)
    app.router.add_post("/api/tasks/{id}/toggle", h_tasks_toggle)
    app.router.add_delete("/api/tasks/{id}", h_tasks_delete)


# ── Legacy migration helper ─────────────────────────────────────────────────

def _migrate_legacy_task(task_def: dict) -> bool:
    """Try to match a legacy 'command' field to a known template. Returns True if migrated."""
    command = task_def.get("command", "").strip()
    if not command:
        return False

    # Simple heuristic matching
    _COMMAND_MAP = {
        "top": "check_cpu",
        "free": "check_memory",
        "df": "check_disk",
        "vcgencmd": "check_temp",
        "uptime": "check_uptime",
        "ip": "check_network",
        "systemctl": "check_services",
        "ping": "ping",
    }
    first_word = command.split()[0] if command.split() else ""
    matched_type = _COMMAND_MAP.get(first_word)
    if matched_type:
        task_def["task_type"] = matched_type
        # Extract ping target from legacy command
        if matched_type == "ping":
            parts = command.split()
            # Find the hostname (last non-flag argument)
            target = parts[-1] if len(parts) > 1 and not parts[-1].startswith("-") else ""
            if target and _validate_ping_target(target) is None:
                task_def["args"] = {"target": target}
        task_def.pop("command", None)
        log.info("[Tasks] Migrated legacy task '%s' → task_type=%s", task_def.get("name"), matched_type)
        return True
    return False
