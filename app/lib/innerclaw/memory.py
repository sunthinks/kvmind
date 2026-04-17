"""
InnerClaw — History Manager (Memory Compression)

Controls conversation history size to prevent token explosion.
When history exceeds threshold, compresses middle turns into a summary
while preserving the first user message and recent turns.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


class HistoryManager:
    """Controls history size. Prevents token explosion in long tasks."""

    MAX_MESSAGES = 20       # compress when exceeded
    KEEP_RECENT = 6         # always preserve last N messages

    def compress_if_needed(self, history: list[dict]) -> list[dict]:
        """Compress history if too long. Returns same or shorter list."""
        if len(history) <= self.MAX_MESSAGES:
            return history

        first = history[0]
        middle = history[1:-self.KEEP_RECENT]
        recent = history[-self.KEEP_RECENT:]

        summary = self._summarize(middle)
        log.info("[HistoryManager] Compressed %d messages → summary + %d recent",
                 len(history), len(recent))

        return [first, {"role": "user", "content": summary}] + recent

    def _summarize(self, messages: list[dict]) -> str:
        """Extract a concise summary from conversation turns.

        Simple version: extract action names + results from tool_result messages.
        Does not use AI (zero cost). Good enough for most tasks.
        """
        actions_done: list[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "tool_result" and isinstance(content, list):
                for part in content:
                    if part.get("type") == "tool_result":
                        try:
                            result = json.loads(part.get("content", "{}"))
                            name = result.get("name", "?")
                            status = result.get("status", "?")
                            inp = result.get("input", {})
                            # Compact summary: "type_text('df -h') → ok"
                            inp_str = str(inp)[:60]
                            actions_done.append(f"{name}({inp_str}) → {status}")
                        except (json.JSONDecodeError, TypeError):
                            pass

            elif role == "assistant" and isinstance(content, str) and content.strip():
                # AI text observation — take first 100 chars
                text = content.strip()[:100]
                if text:
                    actions_done.append(f"AI: {text}")

        if not actions_done:
            return "[Previous turns compressed — no significant actions]"

        lines = "\n".join(f"- {a}" for a in actions_done[-15:])  # cap at 15
        return f"[Summary of {len(actions_done)} previous actions]\n{lines}"
