"""
0.5.25 (replaces M3.4 SQLite-backed StateDB): in-memory dict + atomic JSON
state store for kdkvm device-side state.

Why JSON, not SQLite:

  * State payload is tiny (a few KB of generic kv + a single in-flight RFC 8628
    device_code row + zero-or-one ai_keys per provider). SQLite is overkill.
  * PiKVM mounts ``/`` read-only. Every SQLite write needed ``mount remount,rw``
    + sibling -wal/-shm files. Three iterations (0.5.20 fd leak → 0.5.23 forced
    close → 0.5.24 single long-lived connection) each fixed one symptom and
    introduced another. The 0.5.24 long connection holds -wal/-shm so that
    ``mount remount,ro`` fails ("mount point is busy") and the device floods
    journalctl with EXT4 re-mounted warnings every heartbeat tick.
  * In-memory dict + atomic JSON file completely sidesteps the SQLite/ro-fs
    fight: no sibling files, no fd lifecycle, no WAL checkpoint. Disk write
    only happens **when a value actually changes** — heartbeat ticks where the
    snapshot didn't move are 0-IO.

Disk format (``/var/lib/kdkvm/state.json``)::

    {
      "schema": 1,
      "kv": {<str>: <str>, ...},
      "device_codes": {<key>: {<column>: <value>, ...}, ...},
      "ai_keys": {<provider>: {<column>: <value>, ...}, ...}
    }

Atomic write protocol:

  1. With ``remount_rw('/var/lib/kdkvm/state.json')`` reference-counted helper.
  2. Write JSON payload to ``state.json.tmp``.
  3. ``f.flush()`` + ``os.fsync(fd)``.
  4. ``os.replace('state.json.tmp', 'state.json')`` — atomic on ext4.
  5. ``fsync`` parent dir so the rename actually hits disk (else a power loss
     can yield "old file content but new dirent" — the rename returns success
     before the dirent block lands).

Crash semantics:

  * Crash mid-flush before rename → ``state.json`` is the previous good
    version; the next flush overwrites the .tmp.
  * Crash after dirty in-memory write but before flush → that change is lost.
    All callers tolerate this: ``tunnel_token``/``bound_customer_id`` are
    re-delivered by the next kdcms heartbeat; binding pending lists are
    re-delivered by heartbeat; needs_reactivation/bootstrap_done are written
    by recoverable code paths. We accept "best-effort persistence with
    re-derivation on next heartbeat" as the contract.

Concurrency model:

  * kdkvm runs as a single asyncio event loop. heartbeat is an asyncio task,
    not a thread. handlers are coroutines on the same loop. So state mutations
    are serialised by the loop already.
  * A ``threading.Lock`` is held across every read-modify-write to defend
    against any future ``asyncio.to_thread`` worker that touches state.
  * The CLI binary (``kdkvm tunnel-token``) is a separate process. It reads
    state.json directly without instantiating StateStore (see ``lib.cli``) —
    no init side-effects, no flush.

Migration from legacy state.db (V6 SQLite):

  * If ``state.json`` exists with valid schema=1, load it.
  * Else if ``state.db`` exists (legacy install), read kv/device_codes/ai_keys
    once, write state.json, delete the old db + -wal + -shm. Migration runs
    once per device.
  * Else (clean install), write an empty schema=1 JSON.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .remount import remount_rw

log = logging.getLogger(__name__)

# Path resolution:
#   * KVMIND_STATE_DB env honoured for back-compat (kdkvm-cloudflared.service
#     still sets it). If the value points at a legacy *.db path, we transparently
#     swap the suffix to *.json — operators don't have to rewrite the service
#     file at OTA time.
#   * Default: /var/lib/kdkvm/state.json on ro `/` (still in /var/lib so it
#     survives a kdkvm reinstall and matches the existing parent directory
#     install.sh creates).
_RAW_PATH = os.environ.get("KVMIND_STATE_DB", "/var/lib/kdkvm/state.json")
if _RAW_PATH.endswith(".db"):
    _RAW_PATH = _RAW_PATH[:-3] + ".json"
DEFAULT_STATE_PATH = _RAW_PATH

# Schema version — bump only on a backwards-incompatible structural change.
# Adding new fields inside kv/device_codes/ai_keys is forwards-compatible.
_SCHEMA_VERSION = 1


def _empty_state() -> dict[str, Any]:
    return {
        "schema": _SCHEMA_VERSION,
        "kv": {},
        "device_codes": {},
        "ai_keys": {},
    }


class StateStore:
    """In-memory KV/state store with atomic JSON persistence.

    API-compatible with the retired SQLite-backed ``StateDB``. The retired
    ``state_db`` module re-exports this class so existing imports keep working.
    """

    def __init__(self, path: str = DEFAULT_STATE_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = _empty_state()
        self._load_or_migrate()

    # ── load / migrate ───────────────────────────────────────────────────

    def _load_or_migrate(self) -> None:
        p = Path(self.path)
        # Path 1: existing JSON — load and validate.
        if p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and loaded.get("schema") == _SCHEMA_VERSION:
                    # Defensive: ensure top-level buckets exist even if JSON was
                    # hand-edited or upgraded from a future schema variant.
                    base = _empty_state()
                    base["kv"] = dict(loaded.get("kv", {}))
                    base["device_codes"] = dict(loaded.get("device_codes", {}))
                    base["ai_keys"] = dict(loaded.get("ai_keys", {}))
                    self._data = base
                    return
                log.warning(
                    "[StateStore] state.json schema=%r unexpected; rebuilding",
                    loaded.get("schema") if isinstance(loaded, dict) else type(loaded).__name__,
                )
            except (OSError, json.JSONDecodeError) as e:
                log.warning("[StateStore] load failed (%s); will rebuild", e)

        # Path 2: legacy state.db — one-time migration.
        legacy = p.parent / "state.db"
        if legacy.exists():
            log.info("[StateStore] migrating from legacy SQLite state.db")
            try:
                self._migrate_from_sqlite(legacy)
            except Exception as e:
                # Don't fail startup over a migration hiccup — log and proceed
                # with whatever fields landed.
                log.error("[StateStore] migration partial (%s)", e, exc_info=True)
            with self._lock:
                self._flush_locked(also_unlink_legacy=legacy)
            return

        # Path 3: clean install — persist empty schema so subsequent boots
        # take Path 1 and the JSON file is present for the CLI to read.
        with self._lock:
            self._flush_locked()

    def _migrate_from_sqlite(self, db_path: Path) -> None:
        import sqlite3
        # immutable=1 promises the file won't change during this read; sqlite
        # then opens read-only without creating -wal/-shm, which is exactly
        # what we want on a ro filesystem.
        uri = f"file:{db_path}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        try:
            conn.row_factory = sqlite3.Row
            # kv
            try:
                for row in conn.execute("SELECT k, v FROM kv"):
                    self._data["kv"][row["k"]] = row["v"]
            except sqlite3.OperationalError:
                pass  # table missing in pre-M3 DBs
            # device_codes
            try:
                for row in conn.execute("SELECT * FROM device_codes"):
                    d = {col: row[col] for col in row.keys()}
                    key = d.get("key") or "device"
                    self._data["device_codes"][key] = d
            except sqlite3.OperationalError:
                pass
            # ai_keys
            try:
                for row in conn.execute("SELECT * FROM ai_keys"):
                    d = {col: row[col] for col in row.keys()}
                    provider = d.get("provider")
                    if provider:
                        self._data["ai_keys"][provider] = d
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()

    # ── flush ────────────────────────────────────────────────────────────

    def _flush_locked(self, also_unlink_legacy: Optional[Path] = None) -> None:
        """Write self._data to disk atomically. Caller must hold self._lock.

        ``also_unlink_legacy`` is the legacy SQLite db to unlink in the same
        rw window after the new JSON has landed (used by the migration path).
        Cleanup runs only after rename succeeds, so a crash mid-migration
        leaves the old db intact and the next boot retries cleanly.
        """
        payload = json.dumps(self._data, separators=(",", ":"), sort_keys=True)
        p = Path(self.path)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with remount_rw(self.path):
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
            # fsync parent dir so the rename's dirent change durably hits
            # disk — without it ext4 may report success before the metadata
            # block is written, opening a power-loss window.
            try:
                dir_fd = os.open(str(p.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError as e:
                log.warning("[StateStore] parent fsync skipped (%s)", e)
            if also_unlink_legacy is not None:
                for sibling_suffix in ("", "-wal", "-shm"):
                    leg = Path(str(also_unlink_legacy) + sibling_suffix)
                    try:
                        leg.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        log.warning("[StateStore] could not unlink %s: %s", leg, e)

    # ── generic kv bag ───────────────────────────────────────────────────
    #
    # The hot path. heartbeat writes 5 keys per tick (60s default, 1s during
    # binding). Most ticks the values don't change — we early-out before any
    # disk I/O so remount_rw is never invoked.

    def kv_set(self, k: str, v: str) -> None:
        with self._lock:
            if self._data["kv"].get(k) == v:
                return
            self._data["kv"][k] = v
            self._flush_locked()

    def kv_get(self, k: str) -> Optional[str]:
        # Reads don't need the lock — Python dict reads are atomic under GIL,
        # and we never mutate the dict from outside _lock anyway. Skipping the
        # lock keeps kv_get cheap (microseconds) on the heartbeat hot path.
        return self._data["kv"].get(k)

    def kv_delete(self, k: str) -> None:
        with self._lock:
            if k not in self._data["kv"]:
                return
            del self._data["kv"][k]
            self._flush_locked()

    # ── device_codes (RFC 8628) — REMOVED 2026-04-26 (TD-41) ─────────────
    #
    # The OAuth 2.0 Device Authorization Grant flow that this bucket served
    # was retired in V13 (kdcms migration) when device authentication moved
    # to per-request Ed25519 signatures. The save/load/touch/clear methods
    # have been removed — no production caller in kdkvm references them
    # (verified by grep against app/), and the old SQLite migration path in
    # _migrate_from_sqlite still copies any legacy `device_codes` table
    # contents into the JSON dict so on-disk state is preserved for any
    # device that hasn't been wiped post-V6.
    #
    # The `device_codes` key in _empty_state() is kept as an empty dict so
    # state.json layout stays forward/backward compatible — old kdkvm
    # binaries reading this file find an empty dict instead of a missing
    # key, and new callers (none) would find the same. Removing the key
    # entirely would be a schema bump (_SCHEMA_VERSION increment) for a
    # cosmetic gain; not worth it.

    # ── ai_keys (provider API keys, plaintext) ───────────────────────────

    def save_ai_key(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
    ) -> None:
        now = int(time.time())
        record = {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "default_model": default_model,
            "updated_at": now,
        }
        with self._lock:
            existing = self._data["ai_keys"].get(provider)
            if existing and {k: existing.get(k) for k in record if k != "updated_at"} == \
                    {k: record[k] for k in record if k != "updated_at"}:
                # Same content, only updated_at would change — skip flush.
                return
            self._data["ai_keys"][provider] = record
            self._flush_locked()

    def load_ai_key(self, provider: str) -> Optional[dict]:
        with self._lock:
            row = self._data["ai_keys"].get(provider)
            return dict(row) if row else None

    def list_ai_keys(self) -> list[dict]:
        with self._lock:
            return [dict(self._data["ai_keys"][p])
                    for p in sorted(self._data["ai_keys"].keys())]

    def delete_ai_key(self, provider: str) -> None:
        with self._lock:
            if provider not in self._data["ai_keys"]:
                return
            del self._data["ai_keys"][provider]
            self._flush_locked()

    # ── needs_reactivation flag ─────────────────────────────────────────
    # Set when heartbeat observes an unrecoverable 401. setup UI reads it via
    # activation_status() and renders a "please re-link on kvmind.com" banner.

    def set_needs_reactivation(self, flag: bool) -> None:
        self.kv_set("needs_reactivation", "true" if flag else "false")

    def get_needs_reactivation(self) -> bool:
        return (self.kv_get("needs_reactivation") or "").lower() == "true"


# ── singleton plumbing ──────────────────────────────────────────────────

_singleton_lock = threading.Lock()
_singleton: Optional[StateStore] = None


def get_state_store(path: Optional[str] = None) -> StateStore:
    """Return the process-wide StateStore singleton.

    Override the path by setting KVMIND_STATE_DB (back-compat env var). If
    ``path`` is passed explicitly it always wins and resets the singleton —
    that's the test-fixture path.
    """
    global _singleton
    with _singleton_lock:
        if path is not None:
            _singleton = StateStore(path)
        elif _singleton is None:
            _singleton = StateStore(DEFAULT_STATE_PATH)
        return _singleton


def reset_singleton() -> None:
    """Test helper — drop the singleton so the next call re-instantiates."""
    global _singleton
    with _singleton_lock:
        _singleton = None


def read_raw(path: str = DEFAULT_STATE_PATH) -> dict[str, Any]:
    """Read state.json without instantiating a StateStore.

    Used by the ``kdkvm`` CLI binary (``tunnel-token``, ``status``) which is
    a separate short-lived process: it must NOT trigger the load-or-create
    side effects of StateStore.__init__ (no flushing an empty schema, no
    legacy-db migration). Returns the parsed dict if the file is present and
    schema-compatible, or an empty schema dict otherwise.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("schema") == _SCHEMA_VERSION:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return _empty_state()
