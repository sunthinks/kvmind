"""Tests for memory_store.py — SQLite-backed long-term memory."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest


from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def _noop_msd_rw(path):
    yield


from lib.memory_store import MemoryStore, CATEGORIES

# Patch the module-level reference that MemoryStore uses
_orig_msd_rw = patch.object(
    sys.modules["lib.memory_store"], "_msd_rw", _noop_msd_rw
)
_orig_msd_rw.start()


@pytest.fixture
def store(tmp_db_path):
    """Create a MemoryStore backed by a temporary SQLite database."""
    return MemoryStore(db_path=tmp_db_path)


def run(coro):
    """Helper to run async coroutines in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSaveAndRecall:
    def test_save_returns_id(self, store):
        mem_id = run(store.save("user_pref", "Prefers dark mode"))

        assert mem_id is not None
        assert isinstance(mem_id, int)

    def test_recall_returns_saved_memory(self, store):
        run(store.save("user_pref", "Prefers dark mode"))

        memories = run(store.recall(limit=10))

        assert len(memories) == 1
        assert memories[0]["category"] == "user_pref"
        assert memories[0]["content"] == "Prefers dark mode"

    def test_save_multiple_and_recall(self, store):
        run(store.save("user_pref", "Dark mode"))
        run(store.save("device_info", "Ubuntu 22.04"))
        run(store.save("knowledge", "Server IP is 10.0.0.1"))

        memories = run(store.recall(limit=10))

        assert len(memories) == 3
        categories = {m["category"] for m in memories}
        assert categories == {"user_pref", "device_info", "knowledge"}

    def test_save_duplicate_increments_access_count(self, store):
        id1 = run(store.save("user_pref", "Prefers dark mode"))
        id2 = run(store.save("user_pref", "Prefers dark mode"))

        # Same memory, same ID
        assert id1 == id2

        memories = run(store.recall(limit=10))
        assert len(memories) == 1
        # access_count incremented: +1 from duplicate save
        # recall SELECT reads before recall UPDATE, so we see the pre-recall value
        assert memories[0]["access_count"] >= 1

    def test_recall_limit(self, store):
        for i in range(20):
            run(store.save("knowledge", f"Fact {i}"))

        memories = run(store.recall(limit=5))

        assert len(memories) == 5

    def test_recall_empty_store(self, store):
        memories = run(store.recall(limit=10))

        assert memories == []


class TestCategoryFiltering:
    def test_invalid_category_defaults_to_knowledge(self, store):
        run(store.save("invalid_cat", "some content"))

        memories = run(store.recall(limit=10))

        assert len(memories) == 1
        assert memories[0]["category"] == "knowledge"

    def test_valid_categories_accepted(self, store):
        for cat in CATEGORIES:
            run(store.save(cat, f"Content for {cat}"))

        memories = run(store.recall(limit=20))
        saved_categories = {m["category"] for m in memories}

        assert saved_categories == CATEGORIES


class TestCleanup:
    def test_cleanup_removes_old_unused_entries(self, store):
        # Save a memory then manually backdate it
        mem_id = run(store.save("knowledge", "Old fact"))

        # Directly manipulate the DB to backdate the entry
        import sqlite3
        from datetime import datetime, timezone, timedelta

        conn = sqlite3.connect(store._db_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        conn.execute(
            "UPDATE memories SET created_at = ?, access_count = 0 WHERE id = ?",
            (old_date, mem_id),
        )
        conn.commit()
        conn.close()

        deleted = run(store.cleanup(days=90))

        assert deleted == 1
        assert run(store.count()) == 0

    def test_cleanup_keeps_recently_created(self, store):
        run(store.save("knowledge", "Recent fact"))

        deleted = run(store.cleanup(days=90))

        assert deleted == 0
        assert run(store.count()) == 1

    def test_cleanup_keeps_accessed_entries(self, store):
        import sqlite3
        from datetime import datetime, timezone, timedelta

        mem_id = run(store.save("knowledge", "Accessed fact"))

        # Backdate but ensure access_count > 0
        conn = sqlite3.connect(store._db_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        conn.execute(
            "UPDATE memories SET created_at = ?, access_count = 5 WHERE id = ?",
            (old_date, mem_id),
        )
        conn.commit()
        conn.close()

        deleted = run(store.cleanup(days=90))

        assert deleted == 0
        assert run(store.count()) == 1


class TestCount:
    def test_count_empty(self, store):
        assert run(store.count()) == 0

    def test_count_after_saves(self, store):
        run(store.save("user_pref", "A"))
        run(store.save("user_pref", "B"))
        run(store.save("user_pref", "C"))

        assert run(store.count()) == 3


class TestClearAll:
    def test_clear_all(self, store):
        run(store.save("user_pref", "A"))
        run(store.save("device_info", "B"))

        deleted = run(store.clear_all())

        assert deleted == 2
        assert run(store.count()) == 0


class TestFormatForPrompt:
    def test_format_empty(self, store):
        result = store.format_for_prompt([])

        assert result == ""

    def test_format_memories(self, store):
        memories = [
            {"category": "user_pref", "content": "Dark mode"},
            {"category": "device_info", "content": "Ubuntu 22.04"},
        ]

        result = store.format_for_prompt(memories)

        assert "- [user_pref] Dark mode" in result
        assert "- [device_info] Ubuntu 22.04" in result
