"""
KVMind — PiKVM Adapter

Implements KVMBackend for PiKVM V3/V4 and compatible devices (BliKVM v1-v3)
that run the kvmd daemon.

kvmd REST/WebSocket API reference:
  GET  /api/streamer/snapshot    → JPEG screenshot
  GET  /api/info                 → device info
  POST /api/hid/events/send_mouse_move   → move mouse
  POST /api/hid/events/send_mouse_button → click
  POST /api/hid/events/send_mouse_wheel  → scroll
  POST /api/hid/events/send_key?key=X&state=1|0  → keypress
  POST /api/atx/power            → power control {action}
  WS   /api/ws                   → real-time event stream
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp

from . import register
from .base import KVMBackend

log = logging.getLogger(__name__)

# kvmd Unix socket — always preferred over TCP/nginx to avoid auth_request loop.
_KVMD_SOCK = Path("/run/kvmd/kvmd.sock")
_MIN_IMAGE_BYTES = 1024
_KVMD_ABS_COORD_MAX = 32767
_SAFE_RELEASE_KEYS = tuple(
    [
        "ControlLeft", "ControlRight",
        "ShiftLeft", "ShiftRight",
        "AltLeft", "AltRight",
        "MetaLeft", "MetaRight",
    ]
    + [f"Key{ch}" for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    + [f"Digit{n}" for n in range(10)]
    + ["Enter", "Tab", "Space", "Escape", "Backspace", "Delete"]
)
_SAFE_RELEASE_BUTTONS = ("left", "right", "middle")

_POWER_ACTION_MAP = {
    # KVMind product semantics → PiKVM kvmd API actions.
    "on": "on",
    "off": "off",
    "reset": "reset_hard",
    "force_off": "off_hard",
    # Compatibility aliases accepted at adapter boundary only.
    "cycle": "reset_hard",
    "off_hard": "off_hard",
    "reset_hard": "reset_hard",
}


@register("pikvm")
class PiKVMAdapter(KVMBackend):
    """KVM backend for devices running kvmd (PiKVM, BliKVM v1-v3)."""

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._session: Optional[aiohttp.ClientSession] = None
        self._use_unix = False
        self._pressed_keys: set[str] = set()
        self._pressed_buttons: set[str] = set()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def open(self) -> None:
        auth = aiohttp.BasicAuth(self._cfg.username, self._cfg.password)
        connector, base_url, use_unix = self._make_connector()
        self._use_unix = use_unix
        self._session = aiohttp.ClientSession(
            base_url=base_url,
            auth=auth,
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "PiKVMAdapter":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def _sess(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("PiKVMAdapter not opened – call open() first")
        return self._session

    def _transport(self) -> str:
        transport = str(getattr(self._cfg, "transport", "unix") or "unix").lower()
        if transport not in ("unix", "tcp"):
            raise ValueError(f"Unsupported kvm.transport: {transport!r} (expected 'unix' or 'tcp')")
        return transport

    def _unix_socket_path(self) -> Path:
        return Path(str(getattr(self._cfg, "unix_socket", str(_KVMD_SOCK)) or _KVMD_SOCK))

    def _make_connector(self):
        """Create a kvmd transport. TCP is explicit only; no silent Nginx fallback."""
        transport = self._transport()
        if transport == "unix":
            sock = self._unix_socket_path()
            if not sock.exists():
                raise RuntimeError(
                    f"kvmd Unix socket not found: {sock}. "
                    "Set kvm.transport: tcp only for explicit remote/debug use."
                )
            log.info("Using kvmd Unix socket: %s", sock)
            return aiohttp.UnixConnector(path=str(sock)), "http://localhost", True

        log.warning("Using kvmd TCP transport: %s (explicit kvm.transport=tcp)", self._cfg.base_url)
        return aiohttp.TCPConnector(ssl=False), self._cfg.base_url, False

    def _p(self, path: str, *, use_unix: Optional[bool] = None) -> str:
        """Translate nginx-style path to kvmd internal path for Unix socket.

        nginx rewrites `/api/xxx` → `/xxx` before proxying to kvmd.
        When using Unix socket we bypass nginx, so strip the prefix ourselves.
        """
        if use_unix is None:
            use_unix = self._use_unix
        if use_unix and path.startswith("/api/"):
            return path[4:]  # "/api/info" → "/info"
        return path

    @staticmethod
    def _pct_to_kvmd_abs(value: float) -> int:
        """Map KVMind top-left percentage coordinates to kvmd centered absolute coordinates."""
        clamped = max(0.0, min(100.0, float(value)))
        return int(round((clamped - 50.0) / 50.0 * _KVMD_ABS_COORD_MAX))

    @staticmethod
    def _validate_snapshot(data: bytes, content_type: str = "") -> None:
        ctype = (content_type or "").lower().split(";", 1)[0].strip()
        is_jpeg = data.startswith(b"\xff\xd8")
        is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
        ctype_matches = (
            (is_jpeg and ctype in ("", "image/jpeg", "image/jpg"))
            or (is_png and ctype in ("", "image/png"))
        )
        if len(data) >= _MIN_IMAGE_BYTES and ctype_matches:
            return
        prefix = data[:80].decode("utf-8", errors="replace").replace("\n", "\\n")
        raise ValueError(
            f"Invalid snapshot response: content_type={ctype!r}, bytes={len(data)}, prefix={prefix!r}"
        )

    @staticmethod
    def _to_kvmd_power_action(action: str) -> str:
        try:
            return _POWER_ACTION_MAP[action]
        except KeyError as exc:
            raise ValueError(f"Unsupported power action: {action!r}") from exc

    # ── Video ──────────────────────────────────────────────────────────────

    async def snapshot(self, retries: int = 3, delay: float = 1.0) -> bytes:
        """Return current screen as JPEG bytes. Retries on 502/503."""
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                async with self._sess().get(self._p("/api/streamer/snapshot")) as resp:
                    if resp.status in (502, 503) and attempt < retries - 1:
                        log.warning("Snapshot returned %d, retry %d/%d",
                                    resp.status, attempt + 1, retries)
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    data = await resp.read()
                    self._validate_snapshot(data, resp.headers.get("Content-Type", ""))
                    return data
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    log.warning("Snapshot error: %s, retry %d/%d",
                                e, attempt + 1, retries)
                    await asyncio.sleep(delay)
                else:
                    raise
        raise last_err  # type: ignore[misc]

    def stream_urls(self) -> Dict[str, str]:
        return {
            "mjpeg": "/streamer/stream",
            "h264_ws": "/api/media/ws",
            "webrtc_ws": "/api/janus/ws",
            "snapshot": "/streamer/snapshot",
        }

    # ── Device Info ────────────────────────────────────────────────────────

    async def get_info(self) -> Dict[str, Any]:
        async with self._sess().get(self._p("/api/info")) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ── Mouse ──────────────────────────────────────────────────────────────

    async def mouse_move(self, x: float, y: float) -> None:
        # KVMind uses top-left percentages; kvmd absolute HID uses centered coords.
        to_x = self._pct_to_kvmd_abs(x)
        to_y = self._pct_to_kvmd_abs(y)
        async with self._sess().post(
            self._p("/api/hid/events/send_mouse_move"),
            params={"to_x": to_x, "to_y": to_y},
        ) as resp:
            resp.raise_for_status()

    async def mouse_button(self, button: str = "left", pressed: bool = True) -> None:
        if pressed:
            self._pressed_buttons.add(button)
        state = 1 if pressed else 0
        async with self._sess().post(
            self._p("/api/hid/events/send_mouse_button"),
            params={"button": button, "state": state},
        ) as resp:
            resp.raise_for_status()
        if not pressed:
            self._pressed_buttons.discard(button)

    async def mouse_click(self, x: float, y: float, button: str = "left") -> None:
        await self.mouse_move(x, y)
        await asyncio.sleep(0.05)
        try:
            await self.mouse_button(button, True)
            await asyncio.sleep(0.05)
        finally:
            await self._release_button_safely(button)

    async def mouse_double_click(self, x: float, y: float) -> None:
        await self.mouse_click(x, y)
        await asyncio.sleep(0.12)
        await self.mouse_click(x, y)

    async def mouse_wheel(self, delta_x: int = 0, delta_y: int = 0) -> None:
        async with self._sess().post(
            self._p("/api/hid/events/send_mouse_wheel"),
            params={"delta_x": delta_x, "delta_y": delta_y},
        ) as resp:
            resp.raise_for_status()

    # ── Keyboard ───────────────────────────────────────────────────────────

    async def key_press(self, key: str, pressed: bool = True) -> None:
        if pressed:
            self._pressed_keys.add(key)
        state = 1 if pressed else 0
        async with self._sess().post(
            self._p("/api/hid/events/send_key"),
            params={"key": key, "state": state},
        ) as resp:
            resp.raise_for_status()
        if not pressed:
            self._pressed_keys.discard(key)

    async def key_tap(self, key: str) -> None:
        try:
            await self.key_press(key, True)
            await asyncio.sleep(0.05)
        finally:
            await self._release_key_safely(key)

    async def key_combo(self, *keys: str) -> None:
        try:
            for k in keys:
                await self.key_press(k, True)
                await asyncio.sleep(0.02)
        finally:
            for k in reversed(keys):
                await self._release_key_safely(k)
                await asyncio.sleep(0.02)

    # Character-to-HID key mappings (class-level constants, built once)
    _CHAR_MAP = {
        "a":"KeyA","b":"KeyB","c":"KeyC","d":"KeyD","e":"KeyE","f":"KeyF",
        "g":"KeyG","h":"KeyH","i":"KeyI","j":"KeyJ","k":"KeyK","l":"KeyL",
        "m":"KeyM","n":"KeyN","o":"KeyO","p":"KeyP","q":"KeyQ","r":"KeyR",
        "s":"KeyS","t":"KeyT","u":"KeyU","v":"KeyV","w":"KeyW","x":"KeyX",
        "y":"KeyY","z":"KeyZ",
        "0":"Digit0","1":"Digit1","2":"Digit2","3":"Digit3","4":"Digit4",
        "5":"Digit5","6":"Digit6","7":"Digit7","8":"Digit8","9":"Digit9",
        " ":"Space","-":"Minus","=":"Equal","[":"BracketLeft","]":"BracketRight",
        ";":"Semicolon","'":"Quote",",":"Comma",".":"Period","/":"Slash",
    }
    _SHIFT_MAP = {
        "!":"Digit1","@":"Digit2","#":"Digit3","$":"Digit4","%":"Digit5",
        "^":"Digit6","&":"Digit7","*":"Digit8","(":"Digit9",")":"Digit0",
        "_":"Minus","+":"Equal","<":"Comma",">":"Period","?":"Slash",
        ":":"Semicolon",'"':"Quote",
    }

    async def type_text(self, text: str) -> None:
        for ch in text:
            lo = ch.lower()
            shift = ch.isupper() or ch in self._SHIFT_MAP
            key = self._CHAR_MAP.get(lo) or self._SHIFT_MAP.get(ch)
            if not key:
                if ch == "\n": key = "Enter"
                elif ch == "\t": key = "Tab"
                else: continue
            try:
                if shift:
                    await self.key_press("ShiftLeft", True)
                    await asyncio.sleep(0.02)
                await self.key_press(key, True)
                await asyncio.sleep(0.02)
            finally:
                await self._release_key_safely(key)
                if shift:
                    await asyncio.sleep(0.02)
                    await self._release_key_safely("ShiftLeft")
            await asyncio.sleep(0.03)

    async def _release_key_safely(self, key: str) -> None:
        try:
            await asyncio.shield(self.key_press(key, False))
        except (Exception, asyncio.CancelledError) as exc:
            log.warning("Failed to release key %s: %s", key, exc)
            self._pressed_keys.discard(key)

    async def _release_button_safely(self, button: str) -> None:
        try:
            await asyncio.shield(self.mouse_button(button, False))
        except (Exception, asyncio.CancelledError) as exc:
            log.warning("Failed to release mouse button %s: %s", button, exc)
            self._pressed_buttons.discard(button)

    async def release_all(self) -> None:
        keys = list(dict.fromkeys([*self._pressed_keys, *_SAFE_RELEASE_KEYS]))
        buttons = list(dict.fromkeys([*self._pressed_buttons, *_SAFE_RELEASE_BUTTONS]))
        for key in keys:
            await self._release_key_safely(key)
        for button in buttons:
            await self._release_button_safely(button)

    # ── Power ──────────────────────────────────────────────────────────────

    async def power_action(self, action: str) -> None:
        kvmd_action = self._to_kvmd_power_action(action)
        async with self._sess().post(
            self._p("/api/atx/power"),
            params={"action": kvmd_action},
        ) as resp:
            resp.raise_for_status()

    # ── Event Stream ───────────────────────────────────────────────────────

    async def event_stream(self) -> AsyncIterator[Dict[str, Any]]:
        auth = aiohttp.BasicAuth(self._cfg.username, self._cfg.password)
        connector, base_url, use_unix = self._make_connector()
        ws_url = f"{base_url}{self._p(self._cfg.ws_path, use_unix=use_unix)}" if use_unix else self._cfg.ws_url
        async with aiohttp.ClientSession(auth=auth, connector=connector) as session:
            async with session.ws_connect(ws_url) as ws:
                log.info("Connected to kvmd WebSocket at %s", ws_url)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            yield json.loads(msg.data)
                        except json.JSONDecodeError:
                            log.warning("Non-JSON WS message: %s", msg.data[:100])
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        log.warning("kvmd WebSocket closed: %s", msg)
                        break
