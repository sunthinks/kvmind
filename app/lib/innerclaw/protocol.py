"""
Protocol validation — validates AI responses against the tool-call protocol.

Manages self-correction state: tracks violations, decides retries,
handles empty/text-only responses with nudging.

Extracted from Runner to encapsulate all correction logic in one place.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class ProtocolValidator:
    """Validates AI tool-call responses and manages self-correction."""

    MAX_CORRECTIONS = 2

    def __init__(self, known_tools: set[str]) -> None:
        self._known_tools = known_tools
        self._corrections = 0
        self._seen_violations: set[str] = set()
        self._text_only_nudged = False

    def validate_tool_calls(self, tool_calls: list[dict]) -> str | None:
        """Validate tool calls against protocol. Returns violation reason or None."""
        for tc in tool_calls:
            name = tc.get("name", "")
            if name not in self._known_tools:
                return f"Unknown tool: {name}"
            args = tc.get("args")
            if not isinstance(args, dict):
                return f"Tool {name}: args is not a dict"
        return None

    def should_retry_violation(self, violation: str) -> dict | None:
        """Check if we should retry after a violation.

        Returns a correction message dict to append to history, or None
        if max retries exceeded (caller should abort).
        """
        if violation in self._seen_violations or self._corrections >= self.MAX_CORRECTIONS:
            return None
        self._seen_violations.add(violation)
        self._corrections += 1
        log.warning(
            "[Protocol] Violation (%d/%d): %s",
            self._corrections, self.MAX_CORRECTIONS, violation,
        )
        return {
            "role": "user",
            "content": (
                f"Protocol error: {violation}. "
                f"Use only these tools: {', '.join(sorted(self._known_tools))}. "
                f"Tool args must be a JSON object. Try again."
            ),
        }

    def handle_empty_response(self) -> dict | None:
        """Handle empty response (no text AND no tools).

        Returns a retry message dict, or None if max retries exceeded.
        """
        if self._corrections >= self.MAX_CORRECTIONS:
            return None
        self._corrections += 1
        log.warning(
            "[Protocol] Empty response, requesting retry (%d/%d)",
            self._corrections, self.MAX_CORRECTIONS,
        )
        return {
            "role": "user",
            "content": "You returned an empty response. Please observe the screenshot and act on the task.",
        }

    def handle_text_only(self, turn: int) -> dict | None:
        """Handle text-only response (text but no tools) mid-task.

        Returns a nudge message dict, or None if no nudge needed
        (caller should accept the text as final answer).
        """
        # Text-only on turn 1 = likely answering a question → accept as done
        # Text-only on turn > 3 = late in task → accept as done
        # Text-only on turn 2-3 and not yet nudged → nudge once
        if turn > 1 and turn <= 3 and not self._text_only_nudged:
            self._text_only_nudged = True
            log.info("[Protocol] Nudging AI to continue (text-only on turn %d)", turn)
            return {
                "role": "user",
                "content": (
                    "You described what you plan to do but did not call any tools. "
                    "If you still have steps to complete, use tool_calls now. "
                    "If the task is fully done, repeat your final answer."
                ),
            }
        return None

    def reset_on_valid(self) -> None:
        """Reset correction state after receiving valid tool calls."""
        self._corrections = 0
        self._seen_violations.clear()
