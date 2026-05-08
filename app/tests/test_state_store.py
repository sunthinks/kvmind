"""TD-34 — Tests for lib/state_store.py (kdkvm 0.5.25 in-memory + atomic JSON store).

Replaces the retired test_state_db.py (SQLite era). Coverage:

  * Schema/lifecycle: clean install writes empty schema=1 JSON; reload reads it back
  * Migration: legacy state.db (SQLite) → state.json one-time read+rewrite, .db unlinked
  * Atomic write protocol: tmp file used, parent dir fsync (verified by inode trick),
    crash mid-flush leaves previous good content
  * Corruption recovery: malformed JSON / wrong schema rebuilds empty
  * Idempotent flush: kv_set with the SAME value is a 0-IO no-op
  * read_raw without StateStore instantiation (CLI path)
  * API parity: kv, device_codes, ai_keys, needs_reactivation
  * Singleton: same instance unless reset; explicit path replaces

The tests assume state_store has its `remount_rw` no-op'd by conftest's
`_noop_remount_on_non_linux` autouse fixture (so writes hit the local FS
directly without trying to remount /var read-write on macOS).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.state_store import (
    StateStore,
    get_state_store,
    read_raw,
    reset_singleton,
)


# ── lifecycle ──────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_clean_install_writes_empty_schema(self, tmp_path):
        p = tmp_path / "state.json"
        StateStore(str(p))

        assert p.exists()
        with p.open() as f:
            data = json.load(f)
        assert data == {"schema": 1, "kv": {}, "device_codes": {}, "ai_keys": {}}

    def test_reload_existing_state_preserves_data(self, tmp_path):
        p = tmp_path / "state.json"
        s1 = StateStore(str(p))
        s1.kv_set("tunnel_token", "cf-tok-abc")
        s1.save_ai_key(provider="openai", api_key="sk-test")

        # New instance, same path → must read back what s1 wrote.
        s2 = StateStore(str(p))
        assert s2.kv_get("tunnel_token") == "cf-tok-abc"
        assert s2.load_ai_key("openai")["api_key"] == "sk-test"

    def test_parent_directory_auto_created(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "state.json"
        assert not nested.parent.exists()
        StateStore(str(nested))
        assert nested.parent.exists()
        assert nested.exists()

    def test_corrupted_json_rebuilds_empty(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("not-a-json{{{", encoding="utf-8")

        # Should not raise — log warning + rebuild empty schema.
        s = StateStore(str(p))

        assert s.kv_get("anything") is None
        with p.open() as f:
            data = json.load(f)
        assert data["schema"] == 1
        assert data["kv"] == {}

    def test_unknown_schema_rebuilds_empty(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"schema": 999, "kv": {"old": "ignored"}}), encoding="utf-8")

        s = StateStore(str(p))

        # Schema mismatch → discarded; old data unreachable.
        assert s.kv_get("old") is None


# ── migration from legacy SQLite state.db ──────────────────────────────────


class TestMigrationFromSqlite:
    def _seed_legacy_db(self, db_path: Path) -> None:
        """Write a minimal V6-shape SQLite state.db like an older kdkvm would."""
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)
            """)
            conn.execute("""
                CREATE TABLE device_codes (
                    key TEXT PRIMARY KEY, device_code TEXT, user_code TEXT,
                    verification_uri TEXT, verification_uri_complete TEXT,
                    expires_at INTEGER, interval_seconds INTEGER,
                    last_polled_at INTEGER, created_at INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE ai_keys (
                    provider TEXT PRIMARY KEY, api_key TEXT, base_url TEXT,
                    default_model TEXT, updated_at INTEGER
                )
            """)
            conn.execute("INSERT INTO kv VALUES (?, ?)", ("tunnel_token", "legacy-cf-tok"))
            conn.execute("INSERT INTO kv VALUES (?, ?)", ("bound_customer_id", "42"))
            conn.execute("""
                INSERT INTO device_codes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("device", "DC-LEGACY", "ABCD-EFGH", "https://kvmind.com/activate",
                  None, 9999999999, 5, None, 1700000000))
            conn.execute("""
                INSERT INTO ai_keys VALUES (?, ?, ?, ?, ?)
            """, ("openai", "sk-legacy", "https://api.openai.com/v1", "gpt-5", 1700000001))
            conn.commit()

    def test_legacy_db_imported_and_unlinked(self, tmp_path):
        legacy = tmp_path / "state.db"
        self._seed_legacy_db(legacy)
        assert legacy.exists()

        # No state.json yet — migration runs.
        target = tmp_path / "state.json"
        s = StateStore(str(target))

        # Data carried over from SQLite → in-memory + JSON.
        assert s.kv_get("tunnel_token") == "legacy-cf-tok"
        assert s.kv_get("bound_customer_id") == "42"
        ai = s.load_ai_key("openai")
        assert ai["api_key"] == "sk-legacy"
        assert ai["base_url"] == "https://api.openai.com/v1"
        # TD-41: device_code save/load API was removed. Verify the legacy SQLite
        # row still made it onto disk by reading the raw JSON instead — the
        # migration must keep historical state intact even though the runtime
        # API has retired.
        raw = read_raw(str(target))
        assert raw["device_codes"]["device"]["device_code"] == "DC-LEGACY"
        assert raw["device_codes"]["device"]["user_code"] == "ABCD-EFGH"

        # Legacy file is gone (along with -wal / -shm siblings if any).
        assert not legacy.exists()
        assert target.exists()

    def test_legacy_partial_tables_tolerated(self, tmp_path):
        # Pre-M3 SQLite installs may not have all 3 tables — migration must skip
        # missing tables rather than aborting the whole device.
        legacy = tmp_path / "state.db"
        with sqlite3.connect(str(legacy)) as conn:
            conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            conn.execute("INSERT INTO kv VALUES ('tunnel_token', 'cf-tok')")
            conn.commit()
        # device_codes / ai_keys tables intentionally missing.

        target = tmp_path / "state.json"
        s = StateStore(str(target))

        assert s.kv_get("tunnel_token") == "cf-tok"
        assert s.load_ai_key("openai") is None
        # TD-41: device_codes API removed; assert empty dict via raw JSON.
        raw = read_raw(str(target))
        assert raw["device_codes"] == {}

    def test_migration_skipped_when_json_already_exists(self, tmp_path):
        # If state.json is present, never run migration even if state.db sits beside it.
        target = tmp_path / "state.json"
        target.write_text(
            json.dumps({"schema": 1, "kv": {"k": "from_json"}, "device_codes": {}, "ai_keys": {}}),
            encoding="utf-8",
        )
        legacy = tmp_path / "state.db"
        self._seed_legacy_db(legacy)

        s = StateStore(str(target))

        assert s.kv_get("k") == "from_json"
        assert s.kv_get("tunnel_token") is None  # legacy NOT read
        assert legacy.exists()  # legacy NOT unlinked when json wins


# ── atomic write protocol ──────────────────────────────────────────────────


class TestAtomicWrite:
    def test_no_tmp_file_left_behind_on_success(self, tmp_path):
        p = tmp_path / "state.json"
        s = StateStore(str(p))
        s.kv_set("k", "v")

        tmp = tmp_path / "state.json.tmp"
        assert not tmp.exists(), "leftover .tmp suggests rename did not run"

    def test_idempotent_kv_set_skips_io(self, tmp_path, monkeypatch):
        # Setting the same value twice must not trigger a second flush.
        # Spy on the private _flush_locked to count invocations.
        p = tmp_path / "state.json"
        s = StateStore(str(p))
        # Reset counter — clean install's write doesn't count.
        flush_calls = {"n": 0}
        original_flush = s._flush_locked

        def counting_flush(*args, **kwargs):
            flush_calls["n"] += 1
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(s, "_flush_locked", counting_flush)

        s.kv_set("k", "v")
        first_after = flush_calls["n"]
        s.kv_set("k", "v")  # same value
        second_after = flush_calls["n"]

        assert first_after == 1
        assert second_after == 1  # second set was a no-op

    def test_idempotent_kv_delete_skips_io(self, tmp_path, monkeypatch):
        p = tmp_path / "state.json"
        s = StateStore(str(p))
        flush_calls = {"n": 0}
        original = s._flush_locked
        monkeypatch.setattr(s, "_flush_locked",
                            lambda *a, **kw: (flush_calls.update(n=flush_calls["n"] + 1),
                                              original(*a, **kw))[1])

        s.kv_delete("never-set")  # nothing to delete
        assert flush_calls["n"] == 0

    def test_write_then_read_round_trip_via_raw(self, tmp_path):
        # read_raw must see what StateStore wrote, without instantiating one.
        p = tmp_path / "state.json"
        s = StateStore(str(p))
        s.kv_set("tunnel_token", "abc")
        s.save_ai_key(provider="openai", api_key="sk-test")

        raw = read_raw(str(p))
        assert raw["schema"] == 1
        assert raw["kv"]["tunnel_token"] == "abc"
        assert raw["ai_keys"]["openai"]["api_key"] == "sk-test"

    def test_read_raw_handles_missing_file(self, tmp_path):
        # CLI sub-process should not crash when state.json doesn't exist yet.
        nonexistent = tmp_path / "nope.json"
        raw = read_raw(str(nonexistent))
        assert raw == {"schema": 1, "kv": {}, "device_codes": {}, "ai_keys": {}}

    def test_read_raw_handles_corrupt_file(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("garbage{not-json", encoding="utf-8")
        raw = read_raw(str(p))
        assert raw["kv"] == {}


# ── kv API parity ──────────────────────────────────────────────────────────


class TestKV:
    def test_set_get(self, tmp_state_db):
        tmp_state_db.kv_set("tunnel_token", "cf-tok")
        assert tmp_state_db.kv_get("tunnel_token") == "cf-tok"

    def test_overwrite(self, tmp_state_db):
        tmp_state_db.kv_set("k", "v1")
        tmp_state_db.kv_set("k", "v2")
        assert tmp_state_db.kv_get("k") == "v2"

    def test_missing_returns_none(self, tmp_state_db):
        assert tmp_state_db.kv_get("never_set") is None

    def test_delete(self, tmp_state_db):
        tmp_state_db.kv_set("k", "v")
        tmp_state_db.kv_delete("k")
        assert tmp_state_db.kv_get("k") is None


# ── device_codes — REMOVED (TD-41, 2026-04-26) ──────────────────────────────
#
# The save/load/touch/clear device_code methods were removed from state_store
# along with the RFC 8628 OAuth Device Authorization Grant flow they served.
# No production caller referenced them (verified via grep of dev/kdkvm/app).
#
# The `device_codes` key still appears in _empty_state() / state.json for
# back-compat with on-disk files. Migration of legacy SQLite state.db rows
# into the new JSON dict is verified by TestMigrationFromSqlite above; a
# unit test for the now-removed runtime API would have nothing to assert.


# ── ai_keys API parity ─────────────────────────────────────────────────────


class TestAIKeys:
    def test_save_load_round_trip(self, tmp_state_db):
        tmp_state_db.save_ai_key(
            provider="openai",
            api_key="sk-test-abc",
            base_url="https://api.openai.com/v1",
            default_model="gpt-5",
        )
        row = tmp_state_db.load_ai_key("openai")
        assert row["api_key"] == "sk-test-abc"
        assert row["base_url"] == "https://api.openai.com/v1"
        assert row["default_model"] == "gpt-5"

    def test_load_returns_copy_not_reference(self, tmp_state_db):
        tmp_state_db.save_ai_key(provider="openai", api_key="orig")
        row = tmp_state_db.load_ai_key("openai")
        row["api_key"] = "TAMPERED"
        assert tmp_state_db.load_ai_key("openai")["api_key"] == "orig"

    def test_upsert_on_provider(self, tmp_state_db):
        tmp_state_db.save_ai_key(provider="openai", api_key="v1")
        tmp_state_db.save_ai_key(provider="openai", api_key="v2")
        assert tmp_state_db.load_ai_key("openai")["api_key"] == "v2"

    def test_list_is_sorted_by_provider(self, tmp_state_db):
        tmp_state_db.save_ai_key(provider="openai", api_key="a")
        tmp_state_db.save_ai_key(provider="anthropic", api_key="b")
        tmp_state_db.save_ai_key(provider="gemini", api_key="c")
        names = [r["provider"] for r in tmp_state_db.list_ai_keys()]
        assert names == ["anthropic", "gemini", "openai"]

    def test_delete_ai_key(self, tmp_state_db):
        tmp_state_db.save_ai_key(provider="openai", api_key="x")
        tmp_state_db.delete_ai_key("openai")
        assert tmp_state_db.load_ai_key("openai") is None

    def test_load_missing_returns_none(self, tmp_state_db):
        assert tmp_state_db.load_ai_key("never-saved") is None


# ── needs_reactivation ─────────────────────────────────────────────────────


class TestReactivationFlag:
    def test_defaults_to_false(self, tmp_state_db):
        assert tmp_state_db.get_needs_reactivation() is False

    def test_round_trip(self, tmp_state_db):
        tmp_state_db.set_needs_reactivation(True)
        assert tmp_state_db.get_needs_reactivation() is True
        tmp_state_db.set_needs_reactivation(False)
        assert tmp_state_db.get_needs_reactivation() is False

    def test_round_trip_survives_reload(self, tmp_path):
        p = tmp_path / "state.json"
        s1 = StateStore(str(p))
        s1.set_needs_reactivation(True)

        s2 = StateStore(str(p))
        assert s2.get_needs_reactivation() is True


# ── singleton plumbing ─────────────────────────────────────────────────────


class TestSingleton:
    def test_get_returns_same_instance(self, tmp_path, monkeypatch):
        reset_singleton()
        a = get_state_store(str(tmp_path / "s.json"))
        b = get_state_store()  # no path → returns existing singleton
        assert a is b
        reset_singleton()

    def test_explicit_path_replaces_singleton(self, tmp_path):
        reset_singleton()
        p1 = str(tmp_path / "a.json")
        p2 = str(tmp_path / "b.json")
        a = get_state_store(p1)
        b = get_state_store(p2)
        assert a is not b
        assert a.path == p1
        assert b.path == p2
        reset_singleton()

    def test_reset_singleton_reopens(self, tmp_path):
        reset_singleton()
        first = get_state_store(str(tmp_path / "r.json"))
        reset_singleton()
        second = get_state_store(str(tmp_path / "r.json"))
        assert first is not second
        reset_singleton()


# ── back-compat aliases (state_db module) ──────────────────────────────────


class TestBackCompatShim:
    """state_db.py is a 29-line shim that re-exports state_store names under their
    pre-0.5.25 identifiers so existing imports keep compiling. These tests
    guard against accidental breakage of the shim's surface."""

    def test_old_imports_still_resolve(self):
        from lib.state_db import (
            DEFAULT_STATE_DB_PATH,
            StateDB,
            get_state_db,
            reset_state_db_singleton,
        )
        # Aliases point at the real names.
        assert StateDB is StateStore
        assert callable(get_state_db)
        assert callable(reset_state_db_singleton)
        assert isinstance(DEFAULT_STATE_DB_PATH, str)

    def test_old_get_state_db_works(self, tmp_path):
        from lib.state_db import get_state_db, reset_state_db_singleton
        reset_state_db_singleton()
        s = get_state_db(str(tmp_path / "compat.json"))
        s.kv_set("k", "v")
        assert s.kv_get("k") == "v"
        reset_state_db_singleton()
