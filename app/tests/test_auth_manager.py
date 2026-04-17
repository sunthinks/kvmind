"""Tests for auth_manager.py — password hashing, rate limiting, lockout."""
import json
import time
from unittest.mock import patch

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.auth_manager import (
    _hash_password, verify_password, change_password,
    is_initialized, needs_password_change, init_auth,
    PBKDF2_ITERATIONS, MAX_FAILED_ATTEMPTS, LOCKOUT_SECONDS,
)


class TestHashPassword:
    def test_consistent_hash(self):
        salt = b"test-salt-1234567890123456789012"
        h1 = _hash_password("mypass", salt)
        h2 = _hash_password("mypass", salt)
        assert h1 == h2

    def test_different_passwords_different_hashes(self):
        salt = b"test-salt-1234567890123456789012"
        h1 = _hash_password("pass1", salt)
        h2 = _hash_password("pass2", salt)
        assert h1 != h2

    def test_different_salts_different_hashes(self):
        s1 = b"salt-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        s2 = b"salt-bbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        h1 = _hash_password("same-pass", s1)
        h2 = _hash_password("same-pass", s2)
        assert h1 != h2

    def test_output_is_hex(self):
        salt = b"test-salt-1234567890123456789012"
        h = _hash_password("pass", salt)
        assert all(c in "0123456789abcdef" for c in h)


class TestVerifyPassword:
    def test_correct_password(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        # Manually init auth
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("correct-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": True,
            "failed_attempts": 0,
            "locked_until": 0,
        }
        auth_file.write_text(json.dumps(data))

        ok, err = verify_password("correct-pass")
        assert ok is True
        assert err is None

    def test_wrong_password(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("correct-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": True,
            "failed_attempts": 0,
            "locked_until": 0,
        }
        auth_file.write_text(json.dumps(data))

        ok, err = verify_password("wrong-pass")
        assert ok is False
        assert "wrong password" in err

    def test_lockout_after_max_failures(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("correct-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": True,
            "failed_attempts": MAX_FAILED_ATTEMPTS - 1,
            "locked_until": 0,
        }
        auth_file.write_text(json.dumps(data))

        ok, err = verify_password("wrong-pass")
        assert ok is False
        assert "locked" in err

    def test_locked_account_rejects_correct_password(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("correct-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": True,
            "failed_attempts": 0,
            "locked_until": time.time() + 600,  # locked for 10 more min
        }
        auth_file.write_text(json.dumps(data))

        ok, err = verify_password("correct-pass")
        assert ok is False
        assert "locked" in err

    def test_uninitialized_auth(self, tmp_auth_dir):
        # auth_file does not exist
        ok, err = verify_password("any")
        assert ok is False
        assert "not initialized" in err


class TestChangePassword:
    def test_successful_change(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("old-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": False,
            "failed_attempts": 0,
            "locked_until": 0,
        }
        auth_file.write_text(json.dumps(data))

        ok, err = change_password("old-pass", "new-secure-pass")
        assert ok is True
        assert err is None

        # Verify new password works
        ok2, _ = verify_password("new-secure-pass")
        assert ok2 is True

    def test_too_short_password(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("old-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": False,
            "failed_attempts": 0,
            "locked_until": 0,
        }
        auth_file.write_text(json.dumps(data))

        ok, err = change_password("old-pass", "short")
        assert ok is False
        assert "at least 8" in err

    def test_wrong_old_password(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        import secrets
        salt = secrets.token_bytes(32)
        pw_hash = _hash_password("old-pass", salt)
        data = {
            "password_hash": pw_hash,
            "password_salt": salt.hex(),
            "password_changed": False,
            "failed_attempts": 0,
            "locked_until": 0,
        }
        auth_file.write_text(json.dumps(data))

        ok, err = change_password("wrong-old", "new-secure-pass")
        assert ok is False


class TestIsInitialized:
    def test_not_initialized_when_no_file(self, tmp_auth_dir):
        assert is_initialized() is False

    def test_initialized_with_hash(self, tmp_auth_dir):
        auth_dir, auth_file = tmp_auth_dir
        data = {"password_hash": "abc123", "password_salt": "def456"}
        auth_file.write_text(json.dumps(data))
        assert is_initialized() is True
