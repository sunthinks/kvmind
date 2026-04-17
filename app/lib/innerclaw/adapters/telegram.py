"""
InnerClaw Adapters — Telegram Bot Adapter

Translates RunnerEvents into Telegram Bot API calls (sendMessage / sendPhoto).

Usage:
    adapter = TelegramAdapter(bot_token="...", chat_id=12345)
    runner = Runner(kvm, ai_client, audit)
    async for event in runner.run(instruction):
        await adapter.send_event(event.as_dict())
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import aiohttp

from .base import BaseAdapter

log = logging.getLogger(__name__)


class TelegramAdapter(BaseAdapter):
    """
    Telegram Bot adapter for InnerClaw.

    Translates RunnerEvents into Telegram Bot API calls.
    Message routing is handled externally by TelegramBot.
    """

    def __init__(self, bot_token: str, chat_id: int) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._api = f"https://api.telegram.org/bot{bot_token}"
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def supports_streaming(self) -> bool:
        return False

    @property
    def supports_images(self) -> bool:
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── BaseAdapter interface ────────────────────────────────────────────────

    async def send_event(self, event: dict) -> None:
        """Convert RunnerEvent to Telegram message(s)."""
        event_type = event.get("event", "")

        if event_type == "ai_text":
            text = event.get("text", "")
            if text and text != "Analyzing task...":
                await self._send_text(text)

        elif event_type == "screenshot":
            screenshot_b64 = event.get("screenshot", "")
            if screenshot_b64:
                await self._send_photo(screenshot_b64, caption="📸")

        elif event_type == "action_start":
            action = event.get("action", "")
            args = event.get("args", {})
            brief = f"⚡ {action}"
            if action == "type_text":
                brief += f": {args.get('text', '')[:60]}"
            elif action in ("mouse_click", "mouse_double"):
                brief += f" ({args.get('x', 0):.0f}, {args.get('y', 0):.0f})"
            elif action == "key_tap":
                brief += f": {args.get('key', '')}"
            await self._send_text(brief)

        elif event_type == "action_done":
            pass  # Don't spam for every action

        elif event_type == "action_error":
            error = event.get("error", "")
            await self._send_text(f"❌ 操作失败: {error}")

        elif event_type == "task_done":
            message = event.get("message", "")
            await self._send_text(f"✅ {message}" if message else "✅ 任务完成")

        elif event_type == "task_error":
            error = event.get("error", "Unknown error")
            await self._send_text(f"❌ {error}")

        elif event_type == "confirm_required":
            action = event.get("action", "")
            await self._send_text(
                f"⚠️ 危险操作 [{action}] 需要确认\n"
                f"回复 yes 执行，no 取消"
            )

    async def receive_message(self) -> str | None:
        """Not used — message routing handled by TelegramBot."""
        return None

    # ── Telegram Bot API calls ───────────────────────────────────────────────

    async def _send_text(self, text: str) -> None:
        """Send a text message via Telegram Bot API."""
        if not text.strip():
            return
        session = await self._get_session()
        try:
            async with session.post(f"{self._api}/sendMessage", json={
                "chat_id": self._chat_id,
                "text": text[:4096],
            }) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("[Telegram] sendMessage failed: %d %s", resp.status, body[:200])
        except Exception as e:
            log.warning("[Telegram] sendMessage error: %s", e)

    async def _send_photo(self, photo_b64: str, caption: str = "") -> None:
        """Send a photo (base64 JPEG) via Telegram Bot API."""
        session = await self._get_session()
        try:
            photo_bytes = base64.b64decode(photo_b64)
            data = aiohttp.FormData()
            data.add_field("chat_id", str(self._chat_id))
            data.add_field("photo", io.BytesIO(photo_bytes),
                           filename="screen.jpg", content_type="image/jpeg")
            if caption:
                data.add_field("caption", caption[:1024])
            async with session.post(f"{self._api}/sendPhoto", data=data) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("[Telegram] sendPhoto failed: %d %s", resp.status, body[:200])
        except Exception as e:
            log.warning("[Telegram] sendPhoto error: %s", e)
