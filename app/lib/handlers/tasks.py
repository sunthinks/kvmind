"""MyClaw scheduled tasks — allowlist-only task engine with JSON persistence.

Tasks execute predefined monitoring commands (no arbitrary shell).
All execution uses create_subprocess_exec (no shell interpretation).

V2 (2026-04-26):
- TaskStore: asyncio-locked, atomic temp+rename JSON store.  Replaces the prior
  read-modify-write race that lost updates under concurrent CRUD.
- TaskScheduler: owns asyncio.Task lifecycle.  Exposed on app["task_scheduler"]
  so subscription/binding handlers can stop tasks the moment entitlement drops
  (previously only checked at startup/create — a paid-tier-revoked device kept
  running tasks until next reboot).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Awaitable, Callable, Optional

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


def _migrate_legacy_task(task_def: dict) -> bool:
    """Try to match a legacy 'command' field to a known template. Returns True if migrated."""
    command = task_def.get("command", "").strip()
    if not command:
        return False

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
        if matched_type == "ping":
            parts = command.split()
            target = parts[-1] if len(parts) > 1 and not parts[-1].startswith("-") else ""
            if target and _validate_ping_target(target) is None:
                task_def["args"] = {"target": target}
        task_def.pop("command", None)
        log.info("[Tasks] Migrated legacy task '%s' → task_type=%s", task_def.get("name"), matched_type)
        return True
    return False


# ── TaskStore: asyncio-locked, atomic JSON persistence ────────────────────────


class TaskStore:
    """Atomic JSON-backed store for scheduled task definitions.

    All read-modify-write operations hold a single asyncio.Lock so concurrent
    HTTP handlers / runner action calls cannot interleave. Writes go through
    a temp-file + os.replace to avoid torn JSON if the process is killed mid-flush.
    The msd_rw context still wraps writes to keep the SD card rw window short.
    """

    def __init__(self, path: str = _TASKS_FILE):
        self._path = path
        self._lock = asyncio.Lock()

    async def list(self) -> list[dict]:
        async with self._lock:
            return self._read_unsafe()

    async def append(self, task_def: dict) -> None:
        async with self._lock:
            tasks = self._read_unsafe()
            tasks.append(task_def)
            self._write_atomic_unsafe(tasks)

    async def toggle(self, tid: str) -> Optional[dict]:
        async with self._lock:
            tasks = self._read_unsafe()
            for t in tasks:
                if t["id"] == tid:
                    t["enabled"] = not t.get("enabled", True)
                    self._write_atomic_unsafe(tasks)
                    return t
            return None

    async def delete(self, tid: str) -> bool:
        async with self._lock:
            tasks = self._read_unsafe()
            new_tasks = [t for t in tasks if t["id"] != tid]
            if len(new_tasks) == len(tasks):
                return False
            self._write_atomic_unsafe(new_tasks)
            return True

    async def update_runtime_state(
        self,
        tid: str,
        last_run_at,
        run_count,
        last_result,
    ) -> None:
        async with self._lock:
            tasks = self._read_unsafe()
            for t in tasks:
                if t["id"] == tid:
                    t["last_run_at"] = last_run_at
                    t["run_count"] = run_count
                    t["last_result"] = last_result
                    self._write_atomic_unsafe(tasks)
                    return

    async def replace_all(self, tasks: list[dict]) -> None:
        async with self._lock:
            self._write_atomic_unsafe(tasks)

    def _read_unsafe(self) -> list[dict]:
        try:
            with open(self._path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write_atomic_unsafe(self, tasks: list[dict]) -> None:
        with msd_rw(self._path):
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = f"{self._path}.tmp.{os.getpid()}"
            try:
                with open(tmp, "w") as f:
                    json.dump(tasks, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path)
            except Exception:
                # best effort cleanup; no leftover .tmp.* on the SD card
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
                raise


# ── TaskScheduler: live asyncio.Task lifecycle ────────────────────────────────


class TaskScheduler:
    """Owns the asyncio.Task lifecycle for scheduled tasks.

    Exposed on app["task_scheduler"] so subscription / binding handlers can
    react to entitlement changes immediately (stop_all when scheduled_tasks
    flips off, start_all_if_entitled when it flips back on).
    """

    def __init__(
        self,
        store: TaskStore,
        cfg,
        build_cmd_fn: Callable[[str, dict | None], list[str] | None] = _build_cmd,
    ):
        self._store = store
        self._cfg = cfg
        self._build_cmd = build_cmd_fn
        self._tasks: dict[str, asyncio.Task] = {}
        self._live_defs: dict[str, dict] = {}

    def is_entitled(self) -> bool:
        return getattr(self._cfg.subscription, "scheduled_tasks", False)

    def is_running(self, tid: str) -> bool:
        return tid in self._tasks

    def start(self, task_def: dict) -> bool:
        """Start a single task. Returns True if the task is now running.

        Idempotent: starting an already-running task cancels the prior loop
        and replaces it (used by toggle to pick up new schedule fields).
        """
        if not self.is_entitled():
            return False
        if not task_def.get("enabled", True):
            return False
        if task_def.get("legacy"):
            return False
        tid = task_def["id"]
        existing = self._tasks.pop(tid, None)
        if existing is not None:
            existing.cancel()
        self._live_defs[tid] = task_def
        self._tasks[tid] = asyncio.ensure_future(self._run_loop(task_def))
        return True

    def stop(self, tid: str) -> bool:
        t = self._tasks.pop(tid, None)
        self._live_defs.pop(tid, None)
        if t is None:
            return False
        t.cancel()
        return True

    async def start_all_if_entitled(self) -> int:
        """Restart all enabled non-legacy tasks. No-op if entitlement is off."""
        if not self.is_entitled():
            return 0
        tasks = await self._store.list()
        count = 0
        for t in tasks:
            if self.start(t):
                count += 1
        return count

    def stop_all(self) -> int:
        """Stop everything regardless of entitlement state. Returns count stopped."""
        tids = list(self._tasks.keys())
        for tid in tids:
            self.stop(tid)
        return len(tids)

    async def shutdown(self) -> None:
        """Graceful shutdown — cancel run loops, wait for them to exit, flush state.

        Order matters and was the source of a 0.5.36 production incident:
        if we flush before cancellation, an active _run_loop may be holding
        TaskStore._lock (or be inside its own update_runtime_state call), and
        the flush coroutine deadlocks waiting for it. systemd then SIGKILLs
        the process at the 90-second TimeoutStopSec boundary. Cancel first,
        await the tasks so they actually unwind their lock guards, then flush
        with no contention.
        """
        if not self._tasks and not self._live_defs:
            return

        # Snapshot live state and pending tasks before cancellation. We can't
        # rely on self._live_defs after stop_all (it pops entries), and we need
        # to await the cancelled tasks to know they've fully exited.
        snapshot = list(self._live_defs.values())
        pending = list(self._tasks.values())

        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._live_defs.clear()

        for live in snapshot:
            tid = live.get("id")
            if not tid:
                continue
            try:
                await self._store.update_runtime_state(
                    tid,
                    last_run_at=live.get("last_run_at"),
                    run_count=live.get("run_count", 0),
                    last_result=live.get("last_result"),
                )
            except Exception as exc:
                log.warning("[Tasks] shutdown flush failed for %s: %s", tid, exc)

    async def _run_loop(self, task_def: dict):
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

            cmd = self._build_cmd(task_type, task_args)
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
                result = "legacy task (disabled)"
            else:
                result = "tick"

            task_def["last_result"] = result
            log.info(
                "[Tasks] run: %s (%s) #%d → %s",
                task_def.get("name", task_id),
                task_id,
                task_def["run_count"],
                result[:80],
            )

            persist_counter += 1
            now = time.time()
            if persist_counter >= _PERSIST_EVERY_N_RUNS or (now - last_persist_at) >= _PERSIST_INTERVAL_S:
                try:
                    await self._store.update_runtime_state(
                        task_id,
                        last_run_at=ts,
                        run_count=task_def["run_count"],
                        last_result=result,
                    )
                except Exception as exc:
                    log.warning("[Tasks] failed to persist for %s: %s", task_id, exc)
                persist_counter = 0
                last_persist_at = now


# ── aiohttp wiring ────────────────────────────────────────────────────────────


def register(app):
    cfg = app["cfg"]
    store = TaskStore()
    scheduler = TaskScheduler(store, cfg)
    app["task_store"] = store
    app["task_scheduler"] = scheduler

    # ── Boot: migrate legacy + start enabled tasks if entitled ──
    async def _on_startup(_app):
        tasks = await store.list()
        migrated = False
        for task_def in tasks:
            if "command" in task_def and "task_type" not in task_def:
                matched = _migrate_legacy_task(task_def)
                if not matched:
                    task_def["legacy"] = True
                    task_def["enabled"] = False
                    log.warning(
                        "[Tasks] Legacy task '%s' disabled (raw command not in allowlist)",
                        task_def.get("name"),
                    )
                migrated = True
        if migrated:
            try:
                await store.replace_all(tasks)
            except Exception as exc:
                log.warning("[Tasks] migration save failed: %s", exc)
        log.info("[Tasks] Loaded %d tasks from disk", len(tasks))

        if scheduler.is_entitled():
            started = await scheduler.start_all_if_entitled()
            log.info("[Tasks] Started %d tasks at boot", started)

    app.on_startup.append(_on_startup)

    # ── Shutdown: cancel run loops, await them, then flush ──
    async def _on_cleanup(_app):
        await scheduler.shutdown()

    app.on_cleanup.append(_on_cleanup)

    # ── Handlers ──────────────────────────────────────────────────────────

    async def h_tasks_list(req: web.Request) -> web.Response:
        tasks = await store.list()
        return json_response({"jobs": tasks, "templates": list(TASK_TEMPLATES.keys())})

    async def h_tasks_create(req: web.Request) -> web.Response:
        if not scheduler.is_entitled():
            return json_response({"error": "scheduled_tasks_not_enabled"}, status=403)

        body = await req.json()
        task_type = body.get("task_type", "")
        if task_type not in TASK_TEMPLATES:
            return json_response(
                {"error": "invalid_task_type", "allowed": list(TASK_TEMPLATES.keys())},
                status=400,
            )

        task_args = body.get("args")
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
        await store.append(task_def)
        scheduler.start(task_def)
        return json_response({"status": "ok", "task": task_def})

    async def h_tasks_toggle(req: web.Request) -> web.Response:
        tid = req.match_info["id"]
        found = await store.toggle(tid)
        if not found:
            return json_response({"error": "not_found"}, status=404)

        if found["enabled"]:
            scheduler.start(found)
        else:
            scheduler.stop(tid)
        return json_response({"status": "ok", "enabled": found["enabled"]})

    async def h_tasks_delete(req: web.Request) -> web.Response:
        tid = req.match_info["id"]
        ok = await store.delete(tid)
        if not ok:
            return json_response({"error": "not_found"}, status=404)
        scheduler.stop(tid)
        return json_response({"status": "ok"})

    # ── Programmatic API (for Runner / internal tools) ─────────────────────

    async def task_create_fn(body: dict) -> dict:
        if not scheduler.is_entitled():
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
        await store.append(task_def)
        scheduler.start(task_def)
        return {"status": "ok", "task": task_def}

    app["task_create_fn"] = task_create_fn

    # ── Route registration ─────────────────────────────────────────────────

    app.router.add_get("/api/tasks", h_tasks_list)
    app.router.add_post("/api/tasks", h_tasks_create)
    app.router.add_post("/api/tasks/{id}/toggle", h_tasks_toggle)
    app.router.add_delete("/api/tasks/{id}", h_tasks_delete)
