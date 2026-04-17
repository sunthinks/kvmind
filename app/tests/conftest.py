"""Shared pytest fixtures for kdkvm tests."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


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
