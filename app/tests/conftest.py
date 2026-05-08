"""Shared pytest fixtures for kdkvm tests."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# Auto-apply to every test: lib.remount._remount shells out to /bin/mount,
# which exists on PiKVM but not on developer Macs (mount lives at /sbin/mount
# on Darwin and the partitions aren't mountable anyway). No-op the subprocess
# call so local `pytest` runs don't require a Linux VM. On the device the
# real binary is present and this patch has no effect.
@pytest.fixture(autouse=True)
def _noop_remount_on_non_linux(monkeypatch):
    if sys.platform == "linux":
        return  # real behaviour on the target platform
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    try:
        from lib import remount as _remount_mod
    except ImportError:
        return
    monkeypatch.setattr(_remount_mod, "_remount", lambda *a, **kw: True)


@pytest.fixture
def tmp_auth_dir(tmp_path):
    """Provide a temp directory for auth.json, patching AUTH_DIR/AUTH_FILE."""
    auth_dir = tmp_path / ".kdkvm"
    auth_dir.mkdir()
    auth_file = auth_dir / "auth.json"
    # Mock _write_auth to write directly (skip MSD remount)
    def mock_write_auth(data):
        auth_dir.mkdir(parents=True, exist_ok=True)
        with open(auth_file, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(auth_file, 0o600)

    with patch("lib.auth_manager.AUTH_DIR", auth_dir), \
         patch("lib.auth_manager.AUTH_FILE", auth_file), \
         patch("lib.auth_manager._LEGACY_AUTH", tmp_path / "nonexist1"), \
         patch("lib.auth_manager._LEGACY_MSD_AUTH", tmp_path / "nonexist2"), \
         patch("lib.auth_manager._write_auth", side_effect=mock_write_auth):
        yield auth_dir, auth_file


@pytest.fixture
def tmp_config_file(tmp_path):
    """Provide a temp config.yaml file."""
    config_file = tmp_path / "config.yaml"
    return config_file


@pytest.fixture
def tmp_db_path(tmp_path):
    """Provide a temporary SQLite database path for MemoryStore."""
    db_dir = tmp_path / ".kdkvm"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "memory.db")


@pytest.fixture
def tmp_state_db(tmp_path, monkeypatch):
    """Provide an isolated state.db singleton per test.

    Sets ``KVMIND_STATE_DB`` so any get_state_db() call without args
    opens a fresh file, and resets the process-wide singleton on enter
    and exit so tests don't leak state between each other.
    """
    import sys, os as _os
    sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), ".."))
    from lib.state_db import reset_state_db_singleton, get_state_db

    state_dir = tmp_path / "var-lib-kdkvm"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "state.db"
    monkeypatch.setenv("KVMIND_STATE_DB", str(db_path))

    # Reload module-level DEFAULT_STATE_DB_PATH — it was captured at import.
    import lib.state_db as state_db_mod
    monkeypatch.setattr(state_db_mod, "DEFAULT_STATE_DB_PATH", str(db_path))

    reset_state_db_singleton()
    db = get_state_db(str(db_path))
    yield db
    reset_state_db_singleton()
