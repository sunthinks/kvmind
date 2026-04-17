"""
KVMind Integration - Device UID Module

Generates and manages unique device identifiers.
UID format: KVM-XXXX-XXXX-XXXX (alphanumeric, uppercase)
Stored at: /etc/kdkvm/device.uid

Note: /etc/kdkvm/ is on the read-only root partition. Writes require
a brief remount rw → write → remount ro cycle.
"""
from __future__ import annotations

import os
import secrets
import string
from pathlib import Path

from .remount import remount_rw

UID_PATH = os.environ.get("KVMIND_UID_PATH", "/etc/kdkvm/device.uid")
UID_CHARS = string.ascii_uppercase + string.digits  # A-Z, 0-9


def _random_block(length: int = 4) -> str:
    """Generate a random alphanumeric block."""
    return "".join(secrets.choice(UID_CHARS) for _ in range(length))


def generate_uid() -> str:
    """Generate a new device UID and persist it to disk.

    Format: KVM-XXXX-XXXX-XXXX
    Creates parent directories if needed.
    Remounts root partition rw briefly for the write.
    Returns the newly generated UID.
    """
    uid = f"KVM-{_random_block()}-{_random_block()}-{_random_block()}"
    p = Path(UID_PATH)
    with remount_rw(str(p)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(uid + "\n")
    return uid


def get_uid() -> str:
    """Return the device UID, generating one on first call.

    Reads from /etc/kdkvm/device.uid if it exists,
    otherwise generates a new UID automatically.
    """
    p = Path(UID_PATH)
    if p.exists():
        content = p.read_text().strip()
        if content:
            return content
    return generate_uid()
