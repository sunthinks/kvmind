"""
Cloud session lifecycle — manages MyClaw cloud session state.

Encapsulates session_id, cloud prompt, and policy in one object.
Runner only needs to check `if cloud:` instead of tracking 3 separate vars.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class CloudSessionResult:
    """Result of starting a cloud session."""
    session_id: str
    prompt: str | None
    policy: dict


class CloudSession:
    """Manages MyClaw cloud session lifecycle."""

    def __init__(self, gateway: object, trigger: str) -> None:
        self._gateway = gateway
        self._trigger = trigger
        self.session_id: str | None = None
        self.prompt: str | None = None
        self.policy: dict = {}

    async def start(self, intent: str) -> bool:
        """Start cloud session. Returns True if session started."""
        result = await self._gateway.start_session(self._trigger, intent)
        if result:
            self.session_id = result.session_id
            self.prompt = result.prompt
            self.policy = result.policy
            log.info("[CloudSession] Started: id=%s", self.session_id)
            return True
        return False

    @property
    def max_action_level(self) -> int:
        return self.policy.get("max_action_level", 1)

    @property
    def device_uid(self) -> str:
        return self._gateway.device_uid

    def check_action_level(self, action_dicts: list[dict]) -> str | None:
        """Returns error string if any action exceeds the allowed level."""
        return self._gateway.check_action_level(action_dicts, self.max_action_level)

    async def sign_actions(self, action_dicts: list[dict]) -> object:
        """Sign actions via the cloud gateway."""
        return await self._gateway.sign_actions(self.session_id, action_dicts)
