"""
Memory Store — SQLite-backed long-term memory for MyClaw.

Stores user preferences, device information, learned knowledge, and
recurring instructions. Memories are injected into the system prompt
so the AI can reference past context.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .base_store import BaseSQLiteStore
from .remount import msd_rw as _msd_rw

log = logging.getLogger(__name__)

# Valid categories
CATEGORIES = {"user_pref", "device_info", "knowledge", "instruction"}


_ACCESS_FLUSH_THRESHOLD = 20  # Flush access counts after this many buffered entries


class MemoryStore(BaseSQLiteStore):
    """SQLite-backed long-term memory."""

    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    last_accessed TEXT,
    access_count INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category, active);
CREATE INDEX IF NOT EXISTS idx_mem_created ON memories(created_at);
"""
    _AUTO_CLEANUP_DAYS = 7

    def __init__(self, db_path: str = "/var/lib/kvmd/msd/.kdkvm/memory.db") -> None:
        super().__init__(db_path)
        # In-memory buffer: memory_id -> incremental access count since last flush
        self._access_buffer: dict[int, int] = {}

    def _sync_save(self, category: str, content: str, source: str = "user_said") -> Optional[int]:
        if not self._disk_ok():
            log.warning("Disk space low, skipping memory save")
            return None
        if category not in CATEGORIES:
            category = "knowledge"
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                now = datetime.now(timezone.utc).isoformat()
                existing = conn.execute(
                    "SELECT id FROM memories WHERE category = ? AND content = ? AND active = 1",
                    (category, content),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                        (now, existing["id"]),
                    )
                    conn.commit()
                    return existing["id"]
                cur = conn.execute(
                    "INSERT INTO memories (category, content, source, created_at, last_accessed) VALUES (?, ?, ?, ?, ?)",
                    (category, content, source, now, now),
                )
                conn.commit()
                log.info("Memory saved: [%s] %s", category, content[:80])
                return cur.lastrowid
            finally:
                conn.close()

    def _flush_access_counts(self) -> None:
        """Batch-write buffered access counts to DB (reduces SD card writes)."""
        if not self._access_buffer:
            return
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                now = datetime.now(timezone.utc).isoformat()
                for mem_id, count in self._access_buffer.items():
                    conn.execute(
                        "UPDATE memories SET last_accessed = ?, access_count = access_count + ? WHERE id = ?",
                        (now, count, mem_id),
                    )
                conn.commit()
            finally:
                conn.close()
        self._access_buffer.clear()

    def _sync_recall(self, limit: int = 10) -> List[dict]:
        # Read-only query — no SD card write
        conn = self._open_conn()
        try:
            rows = conn.execute(
                """SELECT id, category, content, source, created_at, access_count
                   FROM memories WHERE active = 1
                   ORDER BY access_count DESC, created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        # Buffer access counts in memory
        for r in rows:
            self._access_buffer[r["id"]] = self._access_buffer.get(r["id"], 0) + 1

        # Flush to disk only when buffer exceeds threshold
        if len(self._access_buffer) >= _ACCESS_FLUSH_THRESHOLD:
            self._flush_access_counts()

        return [dict(r) for r in rows]

    def _sync_cleanup(self, days: int = 90) -> int:
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                cur = conn.execute(
                    "DELETE FROM memories WHERE active = 1 AND access_count = 0 AND created_at < ?",
                    (cutoff,),
                )
                conn.commit()
                count = cur.rowcount
                if count:
                    log.info("Memory cleanup: deleted %d old unused entries", count)
                return count
            finally:
                conn.close()

    def _sync_count(self) -> int:
        conn = self._open_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM memories WHERE active = 1").fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    # ── Async public API ──

    async def save(self, category: str, content: str, source: str = "user_said") -> Optional[int]:
        return await asyncio.to_thread(self._sync_save, category, content, source)

    async def recall(self, limit: int = 10) -> List[dict]:
        return await asyncio.to_thread(self._sync_recall, limit)

    async def cleanup(self, days: int = 90) -> int:
        return await asyncio.to_thread(self._sync_cleanup, days)

    async def count(self) -> int:
        return await asyncio.to_thread(self._sync_count)

    async def clear_all(self) -> int:
        def _do():
            with _msd_rw(self._db_path):
                conn = self._open_conn(writable=True)
                try:
                    cur = conn.execute("SELECT COUNT(*) FROM memories")
                    n = cur.fetchone()[0]
                    conn.execute("DELETE FROM memories")
                    conn.commit()
                    return n
                finally:
                    conn.close()
        return await asyncio.to_thread(_do)

    def close(self) -> None:
        """Flush buffered access counts before closing."""
        try:
            self._flush_access_counts()
        except Exception as e:
            log.warning("Failed to flush access counts on close: %s", e)

    def format_for_prompt(self, memories: List[dict]) -> str:
        if not memories:
            return ""
        lines = []
        for m in memories:
            lines.append(f"- [{m['category']}] {m['content']}")
        return "\n".join(lines)
