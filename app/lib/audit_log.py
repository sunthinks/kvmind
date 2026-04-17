"""
KVMind Integration - Audit Log Module

Writes structured JSON log entries for every AI action and task.
Used for security auditing, debugging, and compliance.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)


class AuditLog:
    """Thread-safe async audit logger writing NDJSON to a file."""

    def __init__(self, log_path: str, max_size_mb: int = 100) -> None:
        self._path = Path(log_path)
        self._max_bytes = max_size_mb * 1024 * 1024
        self._lock = asyncio.Lock()
        self._recent: List[Dict[str, Any]] = []   # in-memory ring buffer (last 200)
        self._max_recent = 200
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def log(self, event_type: str, data: Dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            **data,
        }
        async with self._lock:
            self._recent.append(entry)
            if len(self._recent) > self._max_recent:
                self._recent.pop(0)
            await self._write(entry)

    async def _write(self, entry: Dict[str, Any]) -> None:
        try:
            # Rotate if too large
            if self._path.exists() and self._path.stat().st_size > self._max_bytes:
                rotated = self._path.with_suffix(
                    f".{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
                )
                self._path.rename(rotated)

            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            log.warning("AuditLog write failed: %s", exc)

    def recent(self, n: int = 50) -> List[Dict[str, Any]]:
        """Return last n log entries (in-memory)."""
        return list(self._recent[-n:])
