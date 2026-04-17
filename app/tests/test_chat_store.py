"""Tests for chat_store.py — SQLite-backed chat history."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest


@contextmanager
def _noop_msd_rw(path):
    yield


# Patch MSD remount before importing
import lib.base_store as _bs_mod
import lib.chat_store as _cs_mod
patch.object(_bs_mod, "_msd_rw", _noop_msd_rw).start()
patch.object(_cs_mod, "_msd_rw", _noop_msd_rw).start()

from lib.chat_store import ChatStore


@pytest.fixture
def store(tmp_db_path):
    return ChatStore(db_path=tmp_db_path)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCreateSession:
    def test_creates_session(self, store):
        run(store.create_session("sess-1"))
        sessions = run(store.get_sessions())
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess-1"
        assert sessions[0]["mode"] == "suggest"
        assert sessions[0]["lang"] == "zh"

    def test_create_with_custom_mode_and_lang(self, store):
        run(store.create_session("sess-2", mode="auto", lang="en"))
        sessions = run(store.get_sessions())
        assert sessions[0]["mode"] == "auto"
        assert sessions[0]["lang"] == "en"

    def test_replace_existing_session(self, store):
        run(store.create_session("sess-r", mode="suggest"))
        run(store.create_session("sess-r", mode="auto"))
        sessions = run(store.get_sessions())
        assert len(sessions) == 1
        assert sessions[0]["mode"] == "auto"


class TestSaveAndGetMessages:
    def test_save_returns_id(self, store):
        run(store.create_session("sess-m"))
        msg_id = run(store.save_message("sess-m", "user", "Hello"))
        assert msg_id is not None
        assert isinstance(msg_id, int)

    def test_get_recent_messages(self, store):
        run(store.create_session("sess-m"))
        run(store.save_message("sess-m", "user", "Hello"))
        run(store.save_message("sess-m", "assistant", "Hi there"))

        messages = run(store.get_recent_messages("sess-m"))
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there"

    def test_message_limit(self, store):
        run(store.create_session("sess-lim"))
        for i in range(30):
            run(store.save_message("sess-lim", "user", f"Msg {i}"))

        messages = run(store.get_recent_messages("sess-lim", limit=5))
        assert len(messages) == 5
        # Should be the most recent 5, in chronological order
        assert messages[-1]["content"] == "Msg 29"

    def test_has_screenshot_flag(self, store):
        run(store.create_session("sess-ss"))
        run(store.save_message("sess-ss", "assistant", "Here's the screen", has_screenshot=True))

        messages = run(store.get_recent_messages("sess-ss"))
        assert messages[0]["has_screenshot"] == 1

    def test_empty_session_returns_empty(self, store):
        run(store.create_session("sess-empty"))
        messages = run(store.get_recent_messages("sess-empty"))
        assert messages == []

    def test_disk_full_skips_save(self, store):
        run(store.create_session("sess-disk"))
        with patch.object(store, "_disk_ok", return_value=False):
            msg_id = run(store.save_message("sess-disk", "user", "Can't save"))
        assert msg_id is None


class TestGetLatestSession:
    def test_no_sessions(self, store):
        result = run(store.get_latest_session())
        assert result is None

    def test_returns_most_recent(self, store):
        run(store.create_session("sess-old"))
        run(store.create_session("sess-new"))
        # sess-new was created last, so it has the latest last_active
        latest = run(store.get_latest_session())
        assert latest == "sess-new"


class TestGetSessions:
    def test_returns_sessions_ordered_by_activity(self, store):
        run(store.create_session("sess-a"))
        run(store.create_session("sess-b"))
        # Add a message to sess-a to make it more recent
        run(store.save_message("sess-a", "user", "activity"))

        sessions = run(store.get_sessions())
        assert len(sessions) == 2
        assert sessions[0]["id"] == "sess-a"  # more recent activity

    def test_limit(self, store):
        for i in range(15):
            run(store.create_session(f"sess-{i}"))

        sessions = run(store.get_sessions(limit=5))
        assert len(sessions) == 5


class TestCleanup:
    def test_removes_old_messages(self, store):
        run(store.create_session("sess-old"))
        run(store.save_message("sess-old", "user", "Old message"))

        # Backdate the message
        conn = sqlite3.connect(store._db_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute("UPDATE chat_messages SET created_at = ?", (old_date,))
        conn.commit()
        conn.close()

        deleted = run(store.cleanup(days=5))
        assert deleted == 1

        # Session should also be cleaned up (no messages left)
        sessions = run(store.get_sessions())
        assert len(sessions) == 0

    def test_keeps_recent_messages(self, store):
        run(store.create_session("sess-recent"))
        run(store.save_message("sess-recent", "user", "Fresh message"))

        deleted = run(store.cleanup(days=5))
        assert deleted == 0

        messages = run(store.get_recent_messages("sess-recent"))
        assert len(messages) == 1
