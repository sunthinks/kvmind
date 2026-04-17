"""Tests for base_store.py — SQLite infrastructure base class."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest


@contextmanager
def _noop_msd_rw(path):
    yield


# Patch before import
import lib.base_store as _bs_mod
_orig = patch.object(_bs_mod, "_msd_rw", _noop_msd_rw)
_orig.start()

from lib.base_store import BaseSQLiteStore


class ConcreteStore(BaseSQLiteStore):
    """Minimal subclass for testing."""
    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS test_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL
);
"""
    _AUTO_CLEANUP_DAYS = 7

    def insert(self, value: str) -> int:
        conn = self._open_conn(writable=True)
        try:
            cur = conn.execute("INSERT INTO test_items (value) VALUES (?)", (value,))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._open_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM test_items").fetchone()[0]
        finally:
            conn.close()


@pytest.fixture
def store(tmp_db_path):
    return ConcreteStore(db_path=tmp_db_path)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestInit:
    def test_default_db_path(self):
        s = BaseSQLiteStore()
        assert "memory.db" in s._db_path

    def test_custom_db_path(self, tmp_db_path):
        s = ConcreteStore(db_path=tmp_db_path)
        assert s._db_path == tmp_db_path

    def test_schema_not_ready_initially(self, tmp_db_path):
        s = ConcreteStore(db_path=tmp_db_path)
        assert s._schema_ready is False


class TestEnsureDir:
    def test_creates_parent_directory(self, tmp_path):
        db_path = str(tmp_path / "sub" / "dir" / "test.db")
        s = ConcreteStore(db_path=db_path)
        s._ensure_dir()
        assert os.path.isdir(str(tmp_path / "sub" / "dir"))

    def test_idempotent(self, tmp_db_path):
        s = ConcreteStore(db_path=tmp_db_path)
        s._ensure_dir()
        s._ensure_dir()  # should not raise


class TestOpenConn:
    def test_creates_schema_on_first_open(self, store):
        conn = store._open_conn()
        try:
            # Table should exist
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='test_items'"
            ).fetchall()
            assert len(rows) == 1
            assert store._schema_ready is True
        finally:
            conn.close()

    def test_schema_only_created_once(self, store):
        conn1 = store._open_conn()
        conn1.close()
        assert store._schema_ready is True

        # Second open should not re-run schema
        conn2 = store._open_conn()
        conn2.close()
        # If schema ran twice it would still work (IF NOT EXISTS), but flag stays True
        assert store._schema_ready is True

    def test_row_factory_is_row(self, store):
        conn = store._open_conn()
        try:
            assert conn.row_factory == sqlite3.Row
        finally:
            conn.close()


class TestDiskOk:
    def test_returns_true_with_plenty_of_space(self, store):
        # tmp dir should have plenty of space
        assert store._disk_ok() is True

    def test_returns_false_when_space_below_threshold(self, store):
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024  # 100 MB < 500 MB threshold
        with patch("shutil.disk_usage", return_value=mock_usage):
            assert store._disk_ok() is False

    def test_returns_true_on_os_error(self, store):
        with patch("shutil.disk_usage", side_effect=OSError("mock")):
            assert store._disk_ok() is True

    def test_triggers_cleanup_below_auto_threshold(self, store):
        mock_usage = MagicMock()
        mock_usage.free = 150 * 1024 * 1024  # 150 MB < 200 MB auto-cleanup threshold
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch.object(store, "_sync_cleanup") as mock_cleanup:
            store._disk_ok()
            mock_cleanup.assert_called_once_with(days=7)


class TestVacuum:
    def test_vacuum_runs(self, store):
        store.insert("test")
        run(store.vacuum())
        # Should still work after vacuum
        assert store.count() == 1


class TestClose:
    def test_close_is_noop(self, store):
        store.close()  # should not raise


class TestConcreteFunctionality:
    def test_insert_and_count(self, store):
        assert store.count() == 0
        store.insert("hello")
        assert store.count() == 1
        store.insert("world")
        assert store.count() == 2
