"""Tests for PiKVM adapter protocol mapping."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config import KVMConfig
from lib.kvm.pikvm import PiKVMAdapter


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class RecordingPiKVMAdapter(PiKVMAdapter):
    def __init__(self):
        self._pressed_keys = set()
        self._pressed_buttons = set()
        self.events = []
        self.cancel_on = None

    async def key_press(self, key: str, pressed: bool = True) -> None:
        self.events.append(("key", key, pressed))
        if self.cancel_on == ("key", key, pressed):
            raise asyncio.CancelledError("test cancellation")

    async def mouse_button(self, button: str = "left", pressed: bool = True) -> None:
        self.events.append(("button", button, pressed))
        if self.cancel_on == ("button", button, pressed):
            raise asyncio.CancelledError("test cancellation")


class TestPiKVMProtocolMapping:
    def test_percent_to_kvmd_absolute_coordinates(self):
        assert PiKVMAdapter._pct_to_kvmd_abs(0) == -32767
        assert PiKVMAdapter._pct_to_kvmd_abs(50) == 0
        assert PiKVMAdapter._pct_to_kvmd_abs(100) == 32767
        assert PiKVMAdapter._pct_to_kvmd_abs(-10) == -32767
        assert PiKVMAdapter._pct_to_kvmd_abs(110) == 32767

    def test_unix_path_strips_api_prefix(self):
        adapter = PiKVMAdapter(KVMConfig())
        assert adapter._p("/api/info", use_unix=True) == "/info"
        assert adapter._p("/api/streamer/snapshot", use_unix=True) == "/streamer/snapshot"
        assert adapter._p("/api/info", use_unix=False) == "/api/info"

    def test_power_action_mapping(self):
        assert PiKVMAdapter._to_kvmd_power_action("on") == "on"
        assert PiKVMAdapter._to_kvmd_power_action("off") == "off"
        assert PiKVMAdapter._to_kvmd_power_action("reset") == "reset_hard"
        assert PiKVMAdapter._to_kvmd_power_action("force_off") == "off_hard"
        assert PiKVMAdapter._to_kvmd_power_action("cycle") == "reset_hard"

    def test_snapshot_validation_accepts_real_image_like_bytes(self):
        PiKVMAdapter._validate_snapshot(b"\xff\xd8" + (b"\x00" * 2048), "image/jpeg")
        PiKVMAdapter._validate_snapshot(b"\x89PNG\r\n\x1a\n" + (b"\x00" * 2048), "image/png")

    def test_snapshot_validation_rejects_login_html(self):
        with pytest.raises(ValueError, match="Invalid snapshot response"):
            PiKVMAdapter._validate_snapshot(b"<html><title>login</title></html>", "text/html")

    def test_snapshot_validation_rejects_wrong_content_type(self):
        with pytest.raises(ValueError, match="Invalid snapshot response"):
            PiKVMAdapter._validate_snapshot(b"\xff\xd8" + (b"\x00" * 2048), "text/html")

    def test_unix_transport_fails_fast_without_socket(self, tmp_path):
        cfg = KVMConfig(unix_socket=str(tmp_path / "missing.sock"))
        adapter = PiKVMAdapter(cfg)

        with pytest.raises(RuntimeError, match="kvmd Unix socket not found"):
            run(adapter.open())

    def test_key_combo_releases_keys_when_cancelled_mid_press(self):
        adapter = RecordingPiKVMAdapter()
        adapter.cancel_on = ("key", "KeyC", True)

        with pytest.raises(asyncio.CancelledError):
            run(adapter.key_combo("ControlLeft", "KeyC"))

        assert ("key", "KeyC", False) in adapter.events
        assert ("key", "ControlLeft", False) in adapter.events
