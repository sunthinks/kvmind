"""
KVMind Integration - Authentication Manager

Manages device authentication state via /var/lib/kvmd/msd/.kdkvm/auth.json:
  - Password hashing (PBKDF2-SHA256, 260000 iterations)
  - Login attempt rate limiting (5 failures → 15min lockout)
  - First-login forced password change tracking

File format (auth.json):
{
  "password_hash": "<hex>",
  "password_salt": "<hex>",
  "password_changed": false,
  "failed_attempts": 0,
  "locked_until": 0
}
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

AUTH_DIR = Path("/var/lib/kvmd/msd/.kdkvm")
AUTH_FILE = AUTH_DIR / "auth.json"

# Legacy paths — migrate if exists
_LEGACY_AUTH = Path("/opt/kvmind/kdkvm/config/auth.json")
_LEGACY_MSD_AUTH = Path("/var/lib/kvmd/msd/kdkvm/auth.json")

# Hashing parameters
PBKDF2_ITERATIONS = 260_000
SALT_BYTES = 32
HASH_ALGO = "sha256"

# Lockout parameters
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 900  # 15 minutes


def _hash_password(password: str, salt: bytes) -> str:
    """Hash a password with PBKDF2-SHA256, return hex digest."""
    dk = hashlib.pbkdf2_hmac(
        HASH_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return dk.hex()


def _generate_initial_password() -> str:
    """Generate a random 12-char alphanumeric password for first boot."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _read_auth() -> dict:
    """Read auth.json, return empty dict if missing or corrupt."""
    # Migrate from legacy paths if needed (prefer MSD old path over ancient legacy)
    # MSD partition may be read-only, so we remount rw briefly for migration.
    for legacy in (_LEGACY_MSD_AUTH, _LEGACY_AUTH):
        if not AUTH_FILE.exists() and legacy.exists():
            try:
                import shutil
                from .remount import msd_rw
                with msd_rw(str(AUTH_FILE)):
                    AUTH_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy, AUTH_FILE)
                    os.chmod(AUTH_FILE, 0o600)
                log.info("[AuthManager] Migrated auth.json from %s to %s", legacy, AUTH_FILE)
            except Exception as exc:
                log.warning("[AuthManager] Migration from %s failed: %s", legacy, exc)
    if not AUTH_FILE.exists():
        return {}
    try:
        with open(AUTH_FILE) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("[AuthManager] Failed to read %s: %s", AUTH_FILE, exc)
        return {}


def _write_auth(data: dict) -> None:
    """Write auth.json atomically (write-tmp then rename). Remounts MSD rw/ro."""
    from .remount import msd_rw
    with msd_rw(str(AUTH_FILE)):
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        tmp = AUTH_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.rename(AUTH_FILE)
        os.chmod(AUTH_FILE, 0o600)


def init_auth(force: bool = False) -> str:
    """Initialize auth.json with a random password.

    Returns the plaintext initial password (for display to user).
    If auth.json already exists and force=False, returns empty string.
    """
    if AUTH_FILE.exists() and not force:
        log.info("[AuthManager] auth.json already exists, skipping init")
        return ""

    password = _generate_initial_password()
    salt = secrets.token_bytes(SALT_BYTES)
    password_hash = _hash_password(password, salt)

    data = {
        "password_hash": password_hash,
        "password_salt": salt.hex(),
        "password_changed": False,
        "failed_attempts": 0,
        "locked_until": 0,
    }
    _write_auth(data)
    log.info("[AuthManager] Initialized auth.json (password_changed=false)")
    return password


def verify_password(password: str) -> tuple[bool, Optional[str]]:
    """Verify a password against stored hash.

    Returns (success, error_message).
    On success: (True, None)
    On failure: (False, "reason")
    """
    auth = _read_auth()
    if not auth:
        return False, "auth not initialized"

    # Check lockout
    locked_until = auth.get("locked_until", 0)
    if locked_until > time.time():
        remaining = int(locked_until - time.time())
        return False, f"account locked, retry in {remaining}s"

    # Verify hash
    salt = bytes.fromhex(auth.get("password_salt", ""))
    stored_hash = auth.get("password_hash", "")
    computed = _hash_password(password, salt)

    if not secrets.compare_digest(computed, stored_hash):
        # Increment failed attempts
        failed = auth.get("failed_attempts", 0) + 1
        auth["failed_attempts"] = failed
        if failed >= MAX_FAILED_ATTEMPTS:
            auth["locked_until"] = time.time() + LOCKOUT_SECONDS
            auth["failed_attempts"] = 0
            _write_auth(auth)
            return False, f"too many failures, locked for {LOCKOUT_SECONDS // 60}min"
        _write_auth(auth)
        remaining = MAX_FAILED_ATTEMPTS - failed
        return False, f"wrong password ({remaining} attempts left)"

    # Success — reset failed attempts
    if auth.get("failed_attempts", 0) > 0:
        auth["failed_attempts"] = 0
        auth["locked_until"] = 0
        _write_auth(auth)

    return True, None


def needs_password_change() -> bool:
    """Check if user must change password (first login)."""
    auth = _read_auth()
    return not auth.get("password_changed", True)


def change_password(old_password: str, new_password: str) -> tuple[bool, Optional[str]]:
    """Change the device password.

    Returns (success, error_message).
    """
    if len(new_password) < 8:
        return False, "password must be at least 8 characters"
    if len(new_password) > 128:
        return False, "password too long"

    # Verify old password first
    ok, err = verify_password(old_password)
    if not ok:
        return False, err

    # Set new password
    auth = _read_auth()
    salt = secrets.token_bytes(SALT_BYTES)
    auth["password_hash"] = _hash_password(new_password, salt)
    auth["password_salt"] = salt.hex()
    auth["password_changed"] = True
    auth["failed_attempts"] = 0
    auth["locked_until"] = 0
    _write_auth(auth)
    log.info("[AuthManager] Password changed successfully")
    return True, None


def force_set_password(new_password: str) -> tuple[bool, Optional[str]]:
    """Set password without verifying old password. Only for initial setup."""
    if len(new_password) < 8:
        return False, "password must be at least 8 characters"
    if len(new_password) > 128:
        return False, "password too long"
    auth = _read_auth()
    salt = secrets.token_bytes(SALT_BYTES)
    auth["password_hash"] = _hash_password(new_password, salt)
    auth["password_salt"] = salt.hex()
    auth["password_changed"] = True
    auth["failed_attempts"] = 0
    auth["locked_until"] = 0
    _write_auth(auth)
    log.info("[AuthManager] Password force-set successfully (initial setup)")
    return True, None


def is_initialized() -> bool:
    """Check if auth.json exists and has a password hash."""
    auth = _read_auth()
    return bool(auth.get("password_hash"))
