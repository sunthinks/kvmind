"""
KVMind AI Intents

Minimal intent definitions. Each intent has a name, system prompt,
and optional parser (for text-only responses like ANALYSE).

v6: No more JSON extraction, no plan/replan, no ActionResponse/PlanResponse.
Tool calls come from native API, not text parsing.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ── Response (text-only, for ANALYSE) ────────────────────────────────────────

@dataclass
class AnalysisResponse:
    raw_text: str
    text: str
    memory_ops: list[dict] = field(default_factory=list)


# ── Parser (ANALYSE only) ───────────────────────────────────────────────────

_MEMORY_TAG_RE = re.compile(r"\[MEMORY:\s*(\w+)\s*\|\s*(.+?)\]")
_FENCED_RE = re.compile(r"```(?:json)?\s*\n?.*?```", re.DOTALL)


def parse_text_only(raw: str) -> AnalysisResponse:
    """Strip code fences and extract memory tags from text response."""
    memory_ops: list[dict] = []
    for match in _MEMORY_TAG_RE.finditer(raw):
        memory_ops.append({
            "category": match.group(1).strip(),
            "content": match.group(2).strip(),
        })

    text = _MEMORY_TAG_RE.sub("", raw)
    text = _FENCED_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return AnalysisResponse(raw_text=raw, text=text, memory_ops=memory_ops)


# ── Intent Definition ────────────────────────────────────────────────────────

@dataclass
class AIIntent:
    name: str
    system_prompt: str
    memory_instruction: Optional[str] = None
    parser: Optional[Callable[[str], Any]] = None

    def get_system_prompt(self) -> str:
        """Return hardcoded system prompt for this intent."""
        return self.system_prompt


# ── Memory Instructions ─────────────────────────────────────────────────────

_MEMORY_INSTRUCTION_DECIDE = """

## Long-term Memory
Relevant saved memories may be included below. Use them as context.
Do not create memory tool calls in this mode.
"""

_MEMORY_INSTRUCTION_ANALYSE = """

## Long-term Memory
If the user shares information worth remembering across sessions,
add a tag at the end: [MEMORY: category | content]
Categories: user_pref, device_info, knowledge, instruction
"""


# ── System Prompts (hardcoded fallbacks) ─────────────────────────────────────

_PROMPT_DECIDE = """\
You are MyClaw, an AI agent controlling a remote computer via KVM HID.
You can see the screen via screenshots and control it with keyboard/mouse tools.

## How to Respond

For each turn, you MUST do exactly ONE of:

**A) Use tools** — include tool_calls to act on the computer. You may include a brief text explanation alongside the tool_calls.

**B) Final answer** — respond with text ONLY (no tool_calls) when the task is FULLY complete or you are answering a pure knowledge question.

CRITICAL: If you still have more steps to do, you MUST include tool_calls. Do NOT output text describing your plan without also calling the tools. A response with text but no tool_calls is treated as your FINAL answer — the loop will stop.

## Action Loop
1. Observe the screenshot
2. Decide what to do next
3. Call tools to act (type_text, key_tap, mouse_click, etc.)
4. You'll see a new screenshot with tool results
5. Repeat until done, then give your final answer (text only, no tools)

## Investigation Questions
When the user asks a question that requires checking the system (e.g. "有可以清空的文件吗？", "is disk full?", "what processes are running?"):
- Use tools to run the necessary commands (df, du, ls, ps, etc.)
- Keep investigating until you have enough information
- Then give a complete final answer with your findings

## When Done
Describe the result in plain text. Do NOT use any tools.

## When Stuck
If 2-3 attempts fail, stop and explain. Do NOT use any tools.

## Scheduled Tasks
You have a built-in task scheduler via the `create_task` tool.
When the user asks for periodic/scheduled/cron-like tasks (e.g. "每半小时检查CPU", "monitor disk every hour"):
- Use `create_task` with a `task_type` from: check_cpu, check_memory, check_disk, check_temp, check_uptime, check_network, check_services, ping.
- Do NOT try to install cron, systemd timers, or run arbitrary commands on the remote machine.
- For `ping` tasks, pass `{"target": "8.8.8.8"}` in the `args` parameter.

## Rules
- After type_text, ALWAYS follow with key_tap Enter to execute the command
- NEVER repeat the same tool sequence if it failed
- Verify results by checking the next screenshot
- Coordinates are percentages (0-100)
- type_text only supports ASCII — CJK is NOT supported via KVM HID
"""

_PROMPT_ANALYSE = """\
You are MyClaw, a KVM-based AI assistant for remote server management.
You can see the remote computer's screen via a live screenshot.

When the user asks a question:
- Answer directly based on your knowledge and what you see on screen.
- Reference screen content when relevant.

When asked to analyze the screen:
- Describe what is displayed.
- Note errors, warnings, or issues.
- Suggest recommended next actions.

Respond in plain text only. Do NOT include JSON or tool_calls.
"""


# ── Intent Instances ─────────────────────────────────────────────────────────

INTENT_DECIDE = AIIntent(
    name="decide",
    system_prompt=_PROMPT_DECIDE,
    memory_instruction=_MEMORY_INSTRUCTION_DECIDE,
)

INTENT_ANALYSE = AIIntent(
    name="analyse",
    system_prompt=_PROMPT_ANALYSE,
    memory_instruction=_MEMORY_INSTRUCTION_ANALYSE,
    parser=parse_text_only,
)

# ── OCR Prompt ──────────────────────────────────────────────────────────────

_PROMPT_OCR = """\
You are a precision OCR engine. Extract ALL visible text from the screenshot exactly as displayed.

Rules:
1. Extract every character — letters, numbers, symbols, CJK, etc.
2. Preserve layout: line breaks, indentation, spacing, column alignment.
3. Terminal/console: keep prompt, output, formatting exactly as shown.
4. GUI with multiple regions: extract in reading order (top->bottom, left->right), separate regions with blank lines.
5. Output ONLY extracted text. No commentary, explanation, or translation.
6. Tables/structured data: preserve column alignment with spaces.
7. Unreadable characters: use [?] as placeholder.
"""

INTENT_OCR = AIIntent(
    name="ocr",
    system_prompt=_PROMPT_OCR,
)
