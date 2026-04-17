"""
InnerClaw — Budget (Monotonic Resource Counter)

All counters only increment. No reset method exists.
Once a budget is exhausted, the runner MUST stop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Budget:
    max_actions: int = 60
    max_ai_calls: int = 30
    timeout_seconds: float = 300.0

    # Runtime counters (only increment, never reset)
    actions_used: int = field(default=0, init=False)
    ai_calls_used: int = field(default=0, init=False)
    start_time: float = field(default=0.0, init=False)

    def start(self) -> None:
        self.start_time = time.monotonic()

    def can_act(self) -> bool:
        return self.actions_used < self.max_actions and not self.is_timed_out()

    def can_call_ai(self) -> bool:
        return self.ai_calls_used < self.max_ai_calls and not self.is_timed_out()

    def is_timed_out(self) -> bool:
        if self.start_time == 0.0:
            return False
        return (time.monotonic() - self.start_time) > self.timeout_seconds

    def use_action(self) -> None:
        self.actions_used += 1

    def use_ai_call(self) -> None:
        self.ai_calls_used += 1

    def exhausted_reason(self) -> str | None:
        """Return the first exhausted resource, or None."""
        if self.is_timed_out():
            elapsed = time.monotonic() - self.start_time
            return f"Timeout ({elapsed:.0f}s > {self.timeout_seconds:.0f}s)"
        if self.actions_used >= self.max_actions:
            return f"Max actions reached ({self.max_actions})"
        if self.ai_calls_used >= self.max_ai_calls:
            return f"Max AI calls reached ({self.max_ai_calls})"
        return None
