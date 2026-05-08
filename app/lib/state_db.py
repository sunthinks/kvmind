"""
0.5.25 — back-compat shim. The SQLite-backed StateDB was retired after three
iterations (0.5.20 fd leak → 0.5.23 forced-close regression → 0.5.24 long
connection blocked ``mount remount,ro``) failed to coexist cleanly with PiKVM's
read-only root filesystem.

Replacement: :class:`lib.state_store.StateStore` — in-memory dict + atomic
JSON file persistence. State payload is tiny enough that SQLite was overkill,
and the no-sibling-files design completely sidesteps the WAL-on-ro fight.

This module re-exports the new types under their old names so that existing
``from .state_db import get_state_db, StateDB`` lines keep working without
churn. New code should import from :mod:`lib.state_store` directly.
"""
from __future__ import annotations

from .state_store import (
    DEFAULT_STATE_PATH as DEFAULT_STATE_DB_PATH,  # back-compat name
    StateStore as StateDB,                       # back-compat name
    get_state_store as get_state_db,             # back-compat name
    reset_singleton as reset_state_db_singleton, # back-compat name
)

__all__ = [
    "DEFAULT_STATE_DB_PATH",
    "StateDB",
    "get_state_db",
    "reset_state_db_singleton",
]
