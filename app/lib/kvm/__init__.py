"""
KVMind — KVM Hardware Backend Registry

Usage:
    from lib.kvm import create_backend
    backend = create_backend(cfg.kvm)
    await backend.open()
"""
from __future__ import annotations

import logging
from typing import Dict, Type

from .base import KVMBackend

log = logging.getLogger(__name__)

_REGISTRY: Dict[str, Type[KVMBackend]] = {}


def register(name: str):
    """Decorator to register a KVM backend adapter."""
    def decorator(cls: Type[KVMBackend]) -> Type[KVMBackend]:
        _REGISTRY[name] = cls
        log.debug("Registered KVM backend: %s -> %s", name, cls.__name__)
        return cls
    return decorator


def create_backend(cfg) -> KVMBackend:
    """Instantiate the configured KVM backend.

    Args:
        cfg: KVMConfig with a `backend` field ("pikvm", "nanokvm", "blikvm").
    """
    backend_name = getattr(cfg, "backend", "pikvm")

    # Lazy-import adapters so they self-register
    if backend_name == "pikvm":
        from . import pikvm  # noqa: F401
    elif backend_name == "blikvm":
        # BliKVM running PiKVM OS uses the same kvmd API
        from . import pikvm  # noqa: F401
        backend_name = "pikvm"
    elif backend_name == "nanokvm":
        raise NotImplementedError(
            "NanoKVM support is planned but not yet implemented. "
            "Currently supported: pikvm, blikvm (with PiKVM OS)"
        )

    cls = _REGISTRY.get(backend_name)
    if cls is None:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(
            f"Unknown KVM backend: {backend_name!r}. Available: {available}"
        )

    log.info("Creating KVM backend: %s (%s)", backend_name, cls.__name__)
    return cls(cfg)


__all__ = ["KVMBackend", "create_backend", "register"]
