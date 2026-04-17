"""
InnerClaw Adapters — Transport layer adapters for different input channels.

Each adapter translates between a messaging protocol and RunnerEvents.
"""
from .base import BaseAdapter
from .bridge import WebBridgeAdapter
from .telegram import TelegramAdapter

__all__ = [
    "BaseAdapter",
    "WebBridgeAdapter",
    "TelegramAdapter",
]
