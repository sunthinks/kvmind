"""
InnerClaw — Execution Policy

System-level constraints between AI output and execution.
Not a fallback — a safety net that prevents AI behavioral issues.

Responsibilities:
  1. Dedup consecutive identical actions (AI jitter)
  2. Dedup repeated action groups ([A,B,A,B] → [A,B])
  3. Detect loops (same raw_actions across turns)
  4. Detect stale state (consecutive turns with no screen change)
  5. Budget enforcement
"""
from __future__ import annotations

import logging
from collections import deque

from .tools import Action
from .budget import Budget

log = logging.getLogger(__name__)


class ExecutionPolicy:
    """AI output → system constraints → execution."""

    MAX_CONSECUTIVE_SAME = 3      # same raw_actions N times → abort
    MAX_STALE_TURNS = 3           # N turns with change_type=="none" → abort

    def __init__(self) -> None:
        self._recent_action_sigs: deque[str] = deque(maxlen=20)
        self._stale_count: int = 0

    def optimize(self, actions: list[Action]) -> list[Action]:
        """Dedup and clean actions before execution."""
        if not actions:
            return actions

        # 1. Remove consecutive identical actions (AI jitter)
        deduped: list[Action] = [actions[0]]
        for a in actions[1:]:
            if a.signature() != deduped[-1].signature():
                deduped.append(a)

        # 2. Group pattern dedup: [A,B,A,B] → [A,B]
        n = len(deduped)
        if n >= 4:
            sigs = [a.signature() for a in deduped]
            for group_size in range(2, n // 2 + 1):
                if n % group_size == 0:
                    group = sigs[:group_size]
                    if all(sigs[i] == group[i % group_size] for i in range(group_size, n)):
                        log.info("[Policy] Deduped group: %d → %d actions", n, group_size)
                        deduped = deduped[:group_size]
                        break

        if len(deduped) < len(actions):
            log.info("[Policy] Optimized %d → %d actions", len(actions), len(deduped))

        return deduped

    def should_abort(
        self,
        history: list[dict],
        raw_actions: list[Action],
        budget: Budget,
    ) -> str | None:
        """Check if execution should abort. Called BEFORE optimize, using raw AI output.

        Returns abort reason string, or None to continue.
        """
        # 1. Budget exhaustion
        if not budget.can_act():
            return budget.exhausted_reason()
        if not budget.can_call_ai():
            return budget.exhausted_reason()

        # 2. Loop detection: same raw_actions across consecutive turns
        turn_sig = "|".join(a.signature() for a in raw_actions)
        consecutive = 0
        for prev in reversed(self._recent_action_sigs):
            if prev == turn_sig:
                consecutive += 1
            else:
                break
        self._recent_action_sigs.append(turn_sig)

        if consecutive >= self.MAX_CONSECUTIVE_SAME:
            return f"Loop detected: identical actions {consecutive} consecutive turns"

        return None

    def record_change(self, change_type: str) -> str | None:
        """Record screen change result. Returns abort reason if stale too long."""
        if change_type == "none":
            self._stale_count += 1
            if self._stale_count >= self.MAX_STALE_TURNS:
                return f"Screen unchanged for {self._stale_count} consecutive turns"
        else:
            self._stale_count = 0
        return None

    def reset(self) -> None:
        """Reset state for a new task."""
        self._recent_action_sigs.clear()
        self._stale_count = 0
