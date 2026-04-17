"""
InnerClaw — Intent Gate (Language-Agnostic)

Lightweight AI call to classify user intent BEFORE the main agentic loop.
Three-level classification:

  CHAT       → Pure conversation, no system interaction needed → strip tools
  INVESTIGATE → Question that requires checking the system   → keep tools
  EXECUTE    → Direct command to change the system           → keep tools

Only CHAT strips tools. INVESTIGATE and EXECUTE both enter the agentic loop —
the difference is handled by the DECIDE prompt (which tells the AI to answer
questions without performing destructive actions) and the guardrails (which
block dangerous shell commands at the action level).

Design principles:
  - Language-agnostic: delegates classification to AI, no per-language regex
  - Fail-safe: any error → INVESTIGATE (keep tools, let the AI figure it out)
  - Efficient: text-only (no screenshot), max 80 tokens, 8s timeout
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..model_router import ModelRouter

log = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.70

# The three intents the gate can return
INTENT_CHAT = "CHAT"
INTENT_INVESTIGATE = "INVESTIGATE"
INTENT_EXECUTE = "EXECUTE"

# Only CHAT strips tools — these two keep tools available
_TOOL_INTENTS = {INTENT_INVESTIGATE, INTENT_EXECUTE}

INTENT_GATE_PROMPT = """Classify the user's message into exactly one category. Respond with ONLY valid JSON.

CHAT: Pure conversation or general knowledge question that does NOT require looking at or interacting with the computer. Examples: greetings, "what model are you?", "how does Linux work?", "tell me a joke".

INVESTIGATE: A question that REQUIRES checking the computer to answer — running commands, reading files, or looking at the screen. The user wants information, not changes. Examples: "有可以清空的文件吗？" (needs df/du to answer), "disk usage?", "what processes are running?", "is nginx running?", "ファイルを削除できますか？" (needs to check which files exist).

EXECUTE: A direct command to change or act on the computer. The user wants something done. Examples: "清空所有日志", "delete temp files", "restart nginx", "install htop", "ファイルを削除してください".

{"intent": "CHAT" or "INVESTIGATE" or "EXECUTE", "confidence": 0.0 to 1.0}"""


async def classify_intent(
    router: "ModelRouter",
    message: str,
    timeout: float = 8,
) -> tuple[str, float]:
    """Classify user intent via lightweight AI call.

    Returns:
        (intent, confidence) where intent is CHAT/INVESTIGATE/EXECUTE.
        On any failure, returns (INVESTIGATE, 0.0) — safe default that
        keeps tools available and lets the main AI handle classification.
    """
    try:
        result = await router.send(
            system_prompt=INTENT_GATE_PROMPT,
            messages=[{"role": "user", "content": message}],
            max_tokens=80,
            timeout=timeout,
        )

        raw = result.response.text.strip()

        # Extract JSON from response (handle markdown fencing)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not raw.startswith("{"):
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                raw = raw[start:end]

        data = json.loads(raw)
        intent = data.get("intent", "INVESTIGATE").upper()
        confidence = float(data.get("confidence", 0.0))

        # Normalize intent value
        if intent not in (INTENT_CHAT, INTENT_INVESTIGATE, INTENT_EXECUTE):
            log.warning("[IntentGate] Unknown intent '%s', defaulting to INVESTIGATE", intent)
            return INTENT_INVESTIGATE, 0.0

        log.info("[IntentGate] intent=%s confidence=%.2f msg='%s'",
                 intent, confidence, message[:60])
        return intent, confidence

    except json.JSONDecodeError as e:
        log.warning("[IntentGate] JSON parse failed: %s — raw: %s",
                    e, raw[:100] if 'raw' in dir() else "N/A")
        return INTENT_INVESTIGATE, 0.0
    except Exception as e:
        log.warning("[IntentGate] Gate failed: %s — defaulting to INVESTIGATE", e)
        return INTENT_INVESTIGATE, 0.0
