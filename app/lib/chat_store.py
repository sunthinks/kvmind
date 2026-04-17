"""
Chat Store — SQLite-backed chat history persistence for MyClaw.

Persists chat messages across WebSocket reconnections. Uses the same
database file as MemoryStore (/var/lib/kvmd/msd/.kdkvm/memory.db by default).

Screenshots are NOT stored (too large for device storage). Only a
`has_screenshot` flag is kept.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .base_store import BaseSQLiteStore
from .remount import msd_rw as _msd_rw

log = logging.getLogger(__name__)


class ChatStore(BaseSQLiteStore):
    """SQLite-backed chat history."""

    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_active TEXT NOT NULL,
    mode TEXT DEFAULT 'suggest',
    lang TEXT DEFAULT 'zh'
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    has_screenshot INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at);
"""
    _AUTO_CLEANUP_DAYS = 3

    # ── Sync internals ──

    def _sync_create_session(self, session_id: str, mode: str = "suggest", lang: str = "zh") -> None:
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """INSERT OR REPLACE INTO chat_sessions (id, created_at, last_active, mode, lang)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, now, now, mode, lang),
                )
                conn.commit()
            finally:
                conn.close()

    def _sync_save_message(
        self, session_id: str, role: str, content: str, has_screenshot: bool = False
    ) -> Optional[int]:
        if not self._disk_ok():
            log.warning("Disk space low, skipping chat message save")
            return None
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                now = datetime.now(timezone.utc).isoformat()
                cur = conn.execute(
                    """INSERT INTO chat_messages (session_id, role, content, has_screenshot, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, role, content, 1 if has_screenshot else 0, now),
                )
                conn.execute(
                    "UPDATE chat_sessions SET last_active = ? WHERE id = ?",
                    (now, session_id),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def _sync_get_recent_messages(self, session_id: str, limit: int = 20) -> List[dict]:
        conn = self._open_conn()
        try:
            rows = conn.execute(
                """SELECT role, content, has_screenshot, created_at
                   FROM chat_messages WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()

    def _sync_get_latest_session(self) -> Optional[str]:
        conn = self._open_conn()
        try:
            row = conn.execute(
                "SELECT id FROM chat_sessions ORDER BY last_active DESC LIMIT 1"
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    def _sync_get_sessions(self, limit: int = 10) -> List[dict]:
        conn = self._open_conn()
        try:
            rows = conn.execute(
                """SELECT id, created_at, last_active, mode, lang
                   FROM chat_sessions ORDER BY last_active DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _sync_cleanup(self, days: int = 30) -> int:
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                cur = conn.execute("DELETE FROM chat_messages WHERE created_at < ?", (cutoff,))
                msg_count = cur.rowcount
                conn.execute(
                    "DELETE FROM chat_sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM chat_messages)"
                )
                conn.commit()
                if msg_count:
                    log.info("Chat cleanup: deleted %d messages older than %d days", msg_count, days)
                return msg_count
            finally:
                conn.close()

    # ── Async public API ──

    async def create_session(self, session_id: str, mode: str = "suggest", lang: str = "zh") -> None:
        await asyncio.to_thread(self._sync_create_session, session_id, mode, lang)

    async def save_message(
        self, session_id: str, role: str, content: str, has_screenshot: bool = False
    ) -> Optional[int]:
        return await asyncio.to_thread(self._sync_save_message, session_id, role, content, has_screenshot)

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> List[dict]:
        return await asyncio.to_thread(self._sync_get_recent_messages, session_id, limit)

    async def get_latest_session(self) -> Optional[str]:
        return await asyncio.to_thread(self._sync_get_latest_session)

    async def get_sessions(self, limit: int = 10) -> List[dict]:
        return await asyncio.to_thread(self._sync_get_sessions, limit)

    async def cleanup(self, days: int = 30) -> int:
        return await asyncio.to_thread(self._sync_cleanup, days)

    # ── GDPR Art.17 remote wipe ──

    def _sync_wipe_for_uid(self, customer_uid: Optional[str]) -> int:
        """Delete all chat history on this device. Returns deleted message count.

        P0-1 + P2-9: invoked by the cloud-side GDPR scheduler when a customer's
        deletion request is being executed. The device is bound to exactly one
        customer, so this wipes the entire chat corpus — we don't filter by uid
        in SQL. The uid parameter is logged for audit traceability, proving which
        server-side deletion batch triggered the wipe.
        """
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                cur = conn.execute("DELETE FROM chat_messages")
                msg_count = cur.rowcount if cur.rowcount is not None else 0
                conn.execute("DELETE FROM chat_sessions")
                conn.commit()
                # VACUUM shrinks the file and — critically for SQLCipher — rewrites
                # pages so deleted cleartext is no longer recoverable via disk
                # forensics. Without this, raw DELETE only flags rows as free.
                try:
                    conn.execute("VACUUM")
                except Exception as exc:
                    log.warning("[ChatStore] VACUUM after wipe failed (non-fatal): %s", exc)
                log.info(
                    "[ChatStore] GDPR wipe complete (customer_uid=%s): deleted %d messages",
                    customer_uid or "(unspecified)",
                    msg_count,
                )
                return msg_count
            finally:
                conn.close()

    async def wipe_for_uid(self, customer_uid: Optional[str] = None) -> int:
        """Async wrapper — see :meth:`_sync_wipe_for_uid`."""
        return await asyncio.to_thread(self._sync_wipe_for_uid, customer_uid)
