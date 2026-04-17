"""
BaseSQLiteStore — shared SQLite infrastructure for device-side stores.

Provides connection management, MSD remount handling, disk space checks,
and vacuum support. Subclasses define their own schema and domain methods.

P2-9: When ``pysqlcipher3`` is importable *and* ``/etc/kdkvm/device.token``
exists, the connection is opened via SQLCipher with a key derived from the
device token via HKDF-SHA256. The encryption is transparent — all SQL
continues to work unchanged. If either prerequisite is missing, the store
falls back to plain ``sqlite3`` and logs a one-time warning, so the device
stays functional even on environments without SQLCipher installed (common
during initial ARM deployment before optional deps are packaged).

================================================================================
R4-L2: ``/etc/kdkvm/device.token`` ROTATION — design trade-off
================================================================================

The SQLCipher key is derived deterministically as::

    key = HKDF-SHA256(
        ikm  = <bytes of /etc/kdkvm/device.token>,
        salt = _HKDF_SALT,
        info = _HKDF_INFO,
        len  = 32,
    )

i.e. the device token is the ONLY input that varies per-device. If the token
file is overwritten with different bytes, the derived key changes, and **all
existing encrypted databases become permanently unreadable** — there is no
password-upgrade path; SQLCipher treats a wrong key as "this file is garbage"
and refuses to open it.

This is deliberate. The two common rotation triggers and how to handle them:

1. Token compromise (the token leaked off-device).
   Correct behaviour is to DROP all previously-encrypted data — the attacker
   presumably snapshotted the DB along with the token. A fresh rotation
   coupled with loss of old history is the desired outcome: the secondary
   disclosure surface (chat history, MyClaw session caches) is closed.

2. Device transfer / factory reset.
   The new owner must not inherit the old owner's chat history. Wiping the
   old DB is the privacy-correct outcome; if operations wants to preserve
   history for the previous owner they must export via the
   ``/api/customer/data-export`` endpoint BEFORE rotation. There is no path
   that simultaneously rotates the token AND preserves old-key ciphertext.

If you ever need to rotate the token *without* losing history (e.g. "we
provisioned the wrong token by mistake and want to keep the 5 minutes of
chat already written"), the manual procedure is:

    # 1. Export with the OLD token still in place (data can be read).
    sqlcipher <db> "PRAGMA key = \"x'<old_hex>'\"; ATTACH DATABASE 'plain.db' \\
        AS plain KEY ''; SELECT sqlcipher_export('plain'); DETACH DATABASE plain;"

    # 2. Swap /etc/kdkvm/device.token on disk.

    # 3. Re-encrypt under the NEW token:
    sqlcipher plain.db "ATTACH DATABASE 'new.db' AS new KEY \"x'<new_hex>'\"; \\
        SELECT sqlcipher_export('new'); DETACH DATABASE new;"

    # 4. mv new.db memory.db && rm plain.db

This is an intentionally-manual, well-documented escape hatch — making the
code auto-migrate on mismatch would silently lose evidence of token tampering,
which is exactly the scenario we want to surface as "DB fails to open".

**Do NOT** attempt automatic re-encryption inside ``_open_conn`` on
"unable-to-decrypt" errors: a forged token + forged DB swap would then be
silently accepted as a migration, defeating the whole security story.

--------------------------------------------------------------------------------
Salt / info constants
--------------------------------------------------------------------------------

``_HKDF_SALT`` and ``_HKDF_INFO`` are schema-version-bound constants, not
secrets. Rotating them has the SAME effect as rotating every device token
simultaneously — the entire device fleet's encrypted DBs become unreadable.
Increment only when doing a *coordinated* break-and-wipe; otherwise treat as
immutable.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from .remount import msd_rw as _msd_rw

log = logging.getLogger(__name__)

# Disk space thresholds (bytes)
_STOP_WRITE_THRESHOLD = 500 * 1024 * 1024   # 500 MB
_AUTO_CLEANUP_THRESHOLD = 200 * 1024 * 1024  # 200 MB

# P2-9: SQLCipher support — populated lazily on first connection.
# A sentinel of "unknown" means we haven't attempted the import yet.
_SQLCIPHER_STATUS: str = "unknown"   # "ok" | "missing" | "no_token" | "plain"
_SQLCIPHER_MODULE = None              # sqlcipher3-binary or pysqlcipher3 module

# HKDF salt/info constants — hard-coded so all devices derive identically.
# Rotating these values would orphan existing encrypted DBs, so treat as
# schema-version-bound constants (not secrets).
_HKDF_SALT = b"kvmind-chat-store-v1"
_HKDF_INFO = b"sqlcipher-key"
_HKDF_LEN = 32   # SQLCipher uses a 256-bit key
_DEVICE_TOKEN_PATH = "/etc/kdkvm/device.token"


def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-SHA256. Stdlib-only so we don't pull in cryptography here."""
    if not salt:
        salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    previous = b""
    counter = 1
    while len(okm) < length:
        previous = hmac.new(prk, previous + info + bytes([counter]), hashlib.sha256).digest()
        okm += previous
        counter += 1
    return okm[:length]


def _try_load_sqlcipher():
    """Return (module, hex_key) on success; (None, None) otherwise.

    Cached via module globals — avoids re-reading the token file and re-importing
    on every connection open. The first call decides the fate of the process:
    if SQLCipher isn't available or the token is missing, we log once and
    every subsequent call silently returns the cached plain-mode result.
    """
    global _SQLCIPHER_STATUS, _SQLCIPHER_MODULE
    if _SQLCIPHER_STATUS != "unknown":
        return _SQLCIPHER_MODULE, getattr(_try_load_sqlcipher, "_key_hex", None)

    token_path = Path(_DEVICE_TOKEN_PATH)
    if not token_path.exists():
        _SQLCIPHER_STATUS = "no_token"
        log.warning(
            "[BaseSQLiteStore] %s not found — chat DB will be stored unencrypted. "
            "This is expected on first boot before device registration.",
            _DEVICE_TOKEN_PATH,
        )
        return None, None

    # Prefer sqlcipher3 (actively maintained binary wheel) over pysqlcipher3.
    module = None
    for mod_name in ("sqlcipher3", "pysqlcipher3.dbapi2"):
        try:
            module = __import__(mod_name, fromlist=["*"])
            break
        except ImportError:
            continue
    if module is None:
        _SQLCIPHER_STATUS = "missing"
        log.warning(
            "[BaseSQLiteStore] Neither sqlcipher3 nor pysqlcipher3 is installed — "
            "chat DB will be stored unencrypted. Install 'sqlcipher3-binary' to enable."
        )
        return None, None

    try:
        token_bytes = token_path.read_bytes().strip()
        if not token_bytes:
            _SQLCIPHER_STATUS = "no_token"
            log.warning("[BaseSQLiteStore] device.token is empty — falling back to plain SQLite.")
            return None, None
        key = _hkdf_sha256(token_bytes, _HKDF_SALT, _HKDF_INFO, _HKDF_LEN)
        _SQLCIPHER_MODULE = module
        _SQLCIPHER_STATUS = "ok"
        _try_load_sqlcipher._key_hex = key.hex()  # type: ignore[attr-defined]
        log.info("[BaseSQLiteStore] SQLCipher enabled — chat history is encrypted at rest.")
        return module, key.hex()
    except Exception as exc:
        _SQLCIPHER_STATUS = "missing"
        log.warning("[BaseSQLiteStore] SQLCipher setup failed: %s — falling back to plain SQLite.", exc)
        return None, None


class BaseSQLiteStore:
    """Base class for SQLite-backed stores on PiKVM's MSD partition."""

    _SCHEMA: str = ""  # Override in subclass
    _AUTO_CLEANUP_DAYS: int = 30  # Override in subclass

    def __init__(self, db_path: str = "/var/lib/kvmd/msd/.kdkvm/memory.db") -> None:
        self._db_path = db_path
        self._schema_ready = False

    def _ensure_dir(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _open_conn(self, writable: bool = False) -> sqlite3.Connection:
        """Open a short-lived connection. Caller must close it after use.

        P2-9: If SQLCipher is available and the device token exists, the
        connection is opened encrypted. The ``PRAGMA key`` is sent BEFORE any
        other statement (SQLCipher requirement). If SQLCipher is unavailable,
        we transparently fall back to plain sqlite3 — see module docstring.
        """
        # MSD lives on a read-only mount. SQLite opens with O_CREAT by default,
        # so even a "read-only" SELECT path needs rw briefly if the DB file
        # doesn't exist yet (first GET /api/ai/memory after a reset, for
        # example). Same applies to first-call schema bootstrap. Writable
        # callers already hold _msd_rw at a higher layer — refcount makes
        # nesting safe.
        db_exists = Path(self._db_path).exists()
        needs_bootstrap = not self._schema_ready or not db_exists
        if needs_bootstrap and not writable:
            with _msd_rw(self._db_path):
                return self._do_open_conn()
        return self._do_open_conn()

    def _do_open_conn(self) -> sqlite3.Connection:
        self._ensure_dir()
        module, key_hex = _try_load_sqlcipher()
        if module is not None and key_hex is not None:
            # SQLCipher DBAPI mirrors sqlite3 so the rest of the class stays
            # unchanged. Note: we cannot mix encrypted and plain SQLite files,
            # so first-boot migration from an existing plain DB would need a
            # dedicated migration step (not auto-attempted here to avoid
            # accidentally wiping user data).
            conn = module.connect(self._db_path, check_same_thread=False)
            # SQLCipher expects the key as "x'HEXDIGITS'" for raw-binary mode —
            # this is stricter than passing a passphrase (no KDF iterations).
            conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
            # Tune for device constraints: cipher_page_size=4096 is the default
            # but we set it explicitly for documentation + future-proofing.
            conn.execute("PRAGMA cipher_page_size = 4096")
        else:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if not self._schema_ready:
            conn.executescript(self._SCHEMA)
            self._schema_ready = True
        return conn

    def _disk_ok(self) -> bool:
        """Check if there's enough disk space to write."""
        try:
            st = shutil.disk_usage(Path(self._db_path).parent)
            if st.free < _AUTO_CLEANUP_THRESHOLD:
                self._sync_cleanup(days=self._AUTO_CLEANUP_DAYS)
            return st.free >= _STOP_WRITE_THRESHOLD
        except OSError:
            return True

    def _sync_cleanup(self, days: int = 30) -> int:
        """Override in subclass to implement cleanup logic."""
        return 0

    def _sync_vacuum(self) -> None:
        with _msd_rw(self._db_path):
            conn = self._open_conn(writable=True)
            try:
                conn.execute("VACUUM")
            finally:
                conn.close()

    async def vacuum(self) -> None:
        """Reclaim unused disk space."""
        await asyncio.to_thread(self._sync_vacuum)

    def close(self) -> None:
        pass  # No persistent connection to close
