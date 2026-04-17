"""
InnerClaw Adapters — Base Adapter ABC

All channel adapters (Web, Telegram, LINE, WeChat) implement this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAdapter(ABC):
    """Abstract base for messaging channel adapters."""

    @abstractmethod
    async def send_event(self, event: dict) -> None:
        """Send a RunnerEvent (as dict) to the client."""
        ...

    @abstractmethod
    async def receive_message(self) -> str | None:
        """Receive a message from the client. Returns None on disconnect."""
        ...

    @property
    def supports_streaming(self) -> bool:
        """Whether this adapter supports streaming text chunks."""
        return False

    @property
    def supports_images(self) -> bool:
        """Whether this adapter can display screenshots."""
        return False
