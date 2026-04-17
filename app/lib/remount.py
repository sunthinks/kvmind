"""
Filesystem remount helpers for PiKVM's read-only root / MSD partitions.

PiKVM runs with read-only root and MSD partitions by default.
Any write operation must briefly remount rw, perform the write, then remount ro.

Usage:
    from .remount import remount_rw, msd_rw

    # For root partition writes (/etc/kdkvm/, /opt/kvmind/, etc.)
    with remount_rw("/etc/kdkvm/config.yaml"):
        Path(path).write_text(data)

    # For MSD partition writes (/var/lib/kvmd/msd/.kdkvm/)
    with msd_rw("/var/lib/kvmd/msd/.kdkvm/memory.db"):
        conn.execute(...)
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

log = logging.getLogger(__name__)

# ── Reference-counted remount tracking ──────────────────────────────────────
# Prevents premature ro when multiple callers nest remount_rw for the same
# mount point.  Only the outermost caller actually issues the mount commands.
#
#   Thread A: remount_rw("/etc/kdkvm/foo")  →  count 0→1 → mount rw
#   Thread B: remount_rw("/etc/kdkvm/bar")  →  count 1→2 → skip (already rw)
#   Thread B: exit                          →  count 2→1 → skip (still in use)
#   Thread A: exit                          →  count 1→0 → mount ro

_sync_lock = threading.Lock()
_sync_refcounts: dict[str, int] = {}       # mount_point → active-caller count

_async_lock: asyncio.Lock | None = None    # lazily created (needs running loop)
_async_refcounts: dict[str, int] = {}


def _get_async_lock() -> asyncio.Lock:
    """Return (and lazily create) the module-level asyncio.Lock."""
    global _async_lock
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    return _async_lock


def find_mount_point(path: str) -> str:
    """Find the mount point for a given path."""
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        path = os.path.dirname(path)
    return path


def _remount(mount_point: str, mode: str) -> bool:
    """Remount a partition with the given mode ('rw' or 'ro').

    Returns True if the remount command succeeded (returncode 0).
    """
    result = subprocess.run(
        ["/bin/mount", "-o", f"remount,{mode}", mount_point],
        capture_output=True, timeout=5,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        log.warning(
            "remount %s %s failed (rc=%d): %s",
            mode, mount_point, result.returncode, stderr,
        )
        return False
    return True


@contextmanager
def remount_rw(path: str) -> Generator[None, None, None]:
    """Briefly remount the partition containing *path* as rw, then restore ro.

    Reference-counted: nested calls for the same partition are safe — only the
    outermost caller actually issues mount commands.
    """
    mount_point = find_mount_point(path)

    with _sync_lock:
        prev = _sync_refcounts.get(mount_point, 0)
        _sync_refcounts[mount_point] = prev + 1
        need_rw = prev == 0

    if need_rw:
        _remount(mount_point, "rw")

    try:
        yield
    finally:
        with _sync_lock:
            cur = _sync_refcounts[mount_point] - 1
            _sync_refcounts[mount_point] = cur
            need_ro = cur == 0
            if cur <= 0:
                _sync_refcounts.pop(mount_point, None)

        if need_ro:
            _remount(mount_point, "ro")


@contextmanager
def msd_rw(db_path: str) -> Generator[None, None, None]:
    """Briefly remount the MSD partition rw, yield, then remount ro.

    Use for writes to /var/lib/kvmd/msd/.kdkvm/ (SQLite, auth.json).
    Shares reference counting with remount_rw.
    """
    with remount_rw(db_path):
        yield


# ── Async variants (for use in async code that needs await between rw/ro) ──

async def _async_remount(mount_point: str, mode: str) -> bool:
    """Async version of _remount — runs mount in a subprocess."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/mount", "-o", f"remount,{mode}", mount_point,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            log.warning(
                "remount %s %s failed (rc=%d): %s",
                mode, mount_point, proc.returncode,
                stderr.decode(errors="replace").strip(),
            )
            return False
        return True
    except asyncio.TimeoutError:
        log.warning("remount %s %s timed out", mode, mount_point)
        return False


@asynccontextmanager
async def async_remount_rw(path: str) -> AsyncGenerator[None, None]:
    """Async version of remount_rw — reference-counted, allows await inside.

    Only the outermost caller for a given mount point actually issues mount
    commands; nested async callers skip the mount/unmount.
    """
    mount_point = find_mount_point(path)
    lock = _get_async_lock()

    async with lock:
        prev = _async_refcounts.get(mount_point, 0)
        _async_refcounts[mount_point] = prev + 1
        need_rw = prev == 0

    if need_rw:
        await _async_remount(mount_point, "rw")

    try:
        yield
    finally:
        async with lock:
            cur = _async_refcounts[mount_point] - 1
            _async_refcounts[mount_point] = cur
            need_ro = cur == 0
            if cur <= 0:
                _async_refcounts.pop(mount_point, None)

        if need_ro:
            await _async_remount(mount_point, "ro")
