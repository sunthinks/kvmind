"""
KVMind — KVM Hardware Abstraction Layer

Defines the KVMBackend abstract base class that all hardware adapters
(PiKVM, BliKVM, NanoKVM, etc.) must implement.

Composite methods (mouse_click, key_tap, etc.) have default implementations
built from abstract primitives. Adapters may override them for efficiency.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional

log = logging.getLogger(__name__)


class NoVideoSignalError(RuntimeError):
    """Raised when the KVM device reports no video input (HDMI unplugged, source off, etc.).

    str(exc) is user-facing (bilingual). Adapters should translate transport-level
    symptoms (ustreamer 502/503, blank frames, etc.) into this exception so the
    Runner's top-level ``except Exception`` emits a friendly message instead of
    leaking ``503, message='Service Unavailable', url='http://localhost/streamer/snapshot'``.
    """

    USER_MSG = "无视频信号 — 请检查 HDMI 连接 / No video signal — please check the HDMI connection"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(self.USER_MSG)


class KVMBackend(ABC):
    """Abstract interface for KVM hardware control."""

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @abstractmethod
    async def open(self) -> None:
        """Initialize connection to the KVM device."""

    @abstractmethod
    async def close(self) -> None:
        """Release connection resources."""

    # ── Video ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def snapshot(self, retries: int = 3, delay: float = 1.0) -> bytes:
        """Capture a JPEG screenshot from the KVM device."""

    @abstractmethod
    def stream_urls(self) -> Dict[str, str]:
        """Return video stream URLs for the frontend.

        Expected keys (empty string if unsupported):
            mjpeg    — MJPEG HTTP stream
            h264_ws  — H.264 WebSocket stream
            webrtc_ws — WebRTC signaling WebSocket
            snapshot — single-frame JPEG endpoint
        """

    # ── Device Info ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_info(self) -> Dict[str, Any]:
        """Return device status and metadata."""

    # ── Mouse ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def mouse_move(self, x: float, y: float) -> None:
        """Move mouse to (x, y) in 0-100 percentage coordinates."""

    @abstractmethod
    async def mouse_button(self, button: str, pressed: bool) -> None:
        """Press or release a mouse button ("left", "right", "middle")."""

    @abstractmethod
    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        """Scroll the mouse wheel."""

    # ── Keyboard ───────────────────────────────────────────────────────────

    @abstractmethod
    async def key_press(self, key: str, pressed: bool) -> None:
        """Press or release a key (W3C KeyboardEvent.code format)."""

    @abstractmethod
    async def type_text(self, text: str) -> None:
        """Type a string of text character by character."""

    # ── Power ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def power_action(self, action: str) -> None:
        """Execute product-level power control: "on", "off", "reset", "force_off"."""

    # ── Event Stream (optional) ────────────────────────────────────────────

    async def event_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Real-time event stream from the device. Optional."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support event_stream"
        )
        yield  # pragma: no cover — make this an async generator

    async def release_all(self) -> None:
        """Release any pressed HID controls after cancellation or disconnect."""
        return None

    # ── Composite methods (default implementations) ────────────────────────

    async def snapshot_b64(self) -> str:
        """Capture screenshot and return as base64 string."""
        data = await self.snapshot()
        return base64.b64encode(data).decode("ascii")

    async def mouse_click(
        self, x: float, y: float, button: str = "left"
    ) -> None:
        """Move to (x, y) and click."""
        await self.mouse_move(x, y)
        await asyncio.sleep(0.02)
        try:
            await self.mouse_button(button, True)
            await asyncio.sleep(0.02)
        finally:
            await self.mouse_button(button, False)

    async def mouse_double_click(self, x: float, y: float) -> None:
        """Double-click at (x, y)."""
        await self.mouse_click(x, y)
        await asyncio.sleep(0.05)
        await self.mouse_click(x, y)

    async def key_tap(self, key: str) -> None:
        """Tap a key (press + release)."""
        try:
            await self.key_press(key, True)
            await asyncio.sleep(0.02)
        finally:
            await self.key_press(key, False)

    async def key_combo(self, *keys: str) -> None:
        """Press a key combination (hold all, then release in reverse)."""
        try:
            for k in keys:
                await self.key_press(k, True)
                await asyncio.sleep(0.02)
        finally:
            for k in reversed(keys):
                await self.key_press(k, False)
                await asyncio.sleep(0.02)
