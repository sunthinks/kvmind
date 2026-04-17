"""
InnerClaw — Guardrails (Safety Control)

Hard-coded safety rules that the LLM cannot override:
  1. Action whitelist — only known actions allowed
  2. Dangerous actions — require user confirmation (power)
  3. Shell command detection — type_text containing rm -rf, shutdown, etc.
  4. Coordinate bounds — percentages must be 0-100
  5. Rate limiting — max 60 actions/minute
  6. Repeat detection — max 3 identical actions in a row (anti-loop)
  7. Shell prohibition — never allow raw shell action

NOTE: Intent classification (question vs task) is handled by intent_gate.py,
NOT by regex here. This module only inspects tool-call arguments (shell syntax),
which is language-independent.
"""
from __future__ import annotations

import re
import time
from collections import deque


class Guardrails:
    DANGEROUS_ACTIONS = {"power"}
    ALLOWED_ACTIONS = {
        "mouse_click", "mouse_double", "mouse_move",
        "type_text", "key_tap", "key_combo",
        "scroll", "wait", "screenshot", "done",
    }
    MAX_PER_MINUTE = 60
    MAX_REPEAT_SAME = 3

    # Shell command patterns — these match COMMAND SYNTAX, not natural language.
    # Shell syntax is language-independent, so English regex is correct here.
    DANGEROUS_SHELL_PATTERNS = [
        r"\brm\s+(-[rRfi]+\s+)*(/|~|\*)",    # rm -rf /
        r"\brm\s+/",                           # rm /path
        r"\bmkfs\b",                            # format filesystem
        r"\bdd\s+if=",                          # disk dump
        r"\b(shutdown|reboot|poweroff|halt)\b", # system power
        r"\bsystemctl\s+(stop|disable|mask)\s+",# stop services
        r"\b(kill|killall)\s+-9\b",             # force kill
        r"\bchmod\s+(-R\s+)?0?777\b",          # chmod 777
        r"\biptables\s+-F\b",                   # flush firewall
        r">\s*/dev/sd[a-z]",                    # write to raw disk
        r":(){.*};:",                            # fork bomb
        r"\bcurl\b.*\|\s*(ba)?sh",                 # curl pipe to shell
        r"\bwget\b.*\|\s*(ba)?sh",                 # wget pipe to shell
        r"\bpasswd\b",                              # password change
        r"\bcrontab\s+-[re]",                       # crontab remove/edit
    ]

    def __init__(self) -> None:
        self._timestamps: list[float] = []
        self._recent_actions: deque[str] = deque(maxlen=10)

    def check(self, action: dict) -> dict:
        """
        Check if an action is safe to execute.
        Returns {"blocked": False} or {"blocked": True, "reason": ..., "confirm": ...}.
        """
        name = action.get("name", "")
        args = action.get("args", {})

        # 1. Whitelist
        if name not in self.ALLOWED_ACTIONS and name not in self.DANGEROUS_ACTIONS:
            return {"blocked": True, "reason": f"Action [{name}] not in whitelist"}

        # 2. Dangerous actions → require confirmation
        if name in self.DANGEROUS_ACTIONS:
            return {
                "blocked": True,
                "reason": f"Dangerous action [{name}] requires confirmation",
                "confirm": True,
            }

        # 3. Dangerous shell command detection (language-independent)
        if name == "type_text":
            text = args.get("text", "")
            for pattern in self.DANGEROUS_SHELL_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    return {
                        "blocked": True,
                        "reason": f"Potentially dangerous command: {text[:80]}",
                        "confirm": True,
                    }

        # 4. Coordinate bounds (percentage 0-100)
        if name in ("mouse_click", "mouse_double", "mouse_move"):
            x, y = args.get("x", -1), args.get("y", -1)
            if not (0 <= x <= 100 and 0 <= y <= 100):
                return {"blocked": True, "reason": f"Coordinates out of bounds: ({x},{y})"}

        # 5. Rate limiting
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self.MAX_PER_MINUTE:
            return {"blocked": True, "reason": "Rate limit exceeded (60 actions/minute)"}
        self._timestamps.append(now)

        # 6. Repeat detection (anti-loop) — count CONSECUTIVE same actions
        action_sig = f"{name}:{sorted(args.items())}"
        consecutive = 0
        for prev in reversed(self._recent_actions):
            if prev == action_sig:
                consecutive += 1
            else:
                break
        if consecutive >= self.MAX_REPEAT_SAME:
            return {
                "blocked": True,
                "reason": f"Action [{name}] repeated {consecutive} consecutive times, suspected loop",
            }
        self._recent_actions.append(action_sig)

        # 7. Shell prohibition
        if name == "shell":
            return {"blocked": True, "reason": "Shell commands are prohibited"}

        return {"blocked": False}

    def reset(self) -> None:
        """Reset at task start."""
        self._recent_actions.clear()
        self._timestamps.clear()
