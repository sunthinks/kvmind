"""Handler modules for KVMind Bridge server."""

from . import (
    auth, device, dashboard, system,
    subscription, ai_config, websocket, tasks,
)

_MODULES = [
    auth, device, dashboard, system,
    subscription, ai_config, websocket, tasks,
]


def register_all(app):
    """Register all handler routes on the aiohttp app."""
    for mod in _MODULES:
        mod.register(app)
