"""
InnerClaw — Tool Registry & Data Types

System-level tool definitions and strong-typed Action/ActionResult.
Tools are system capabilities, not prompt attributes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ── Strong-typed Action ──────────────────────────────────────────────────────

@dataclass
class Action:
    """A single tool call from the AI provider."""
    id: str         # provider-generated tool_call ID (e.g. "toolu_xxx", "call_xxx")
    name: str       # "type_text", "key_tap", "mouse_click", ...
    input: dict     # {"text": "df -h"}, {"key": "Enter"}, ...

    def signature(self) -> str:
        """Stable string for dedup/loop detection."""
        return f"{self.name}:{json.dumps(self.input, sort_keys=True)}"


@dataclass
class ActionResult:
    """Result of executing a single Action — full causal binding."""
    tool_use_id: str        # correlates back to Action.id
    tool_name: str          # correlates back to Action.name
    input: dict             # correlates back to Action.input (AI can reason)
    status: str             # "ok" | "error" | "blocked" | "rejected"
    error: str | None = None
    duration_ms: int = 0
    before_hash: str = ""   # screenshot hash before execution
    after_hash: str = ""    # screenshot hash after execution
    change_score: float = 0.0   # perceptual diff 0.0~1.0
    change_type: str = "none"   # "none" | "minor" | "major"
    screenshot: str | None = None   # only on last action


def build_tool_result_message(results: list[ActionResult]) -> dict:
    """Build portable tool_result message from ActionResults.

    Standard protocol format — provider layer converts to wire format.
    """
    content: list[dict] = []
    for r in results:
        # Structured result (AI can reason about each action)
        result_text = json.dumps({
            "name": r.tool_name,
            "input": r.input,
            "status": r.status,
            "error": r.error,
            "duration_ms": r.duration_ms,
            "change_type": r.change_type,
        }, ensure_ascii=False)

        content.append({
            "type": "tool_result",
            "tool_use_id": r.tool_use_id,
            "content": result_text,
        })

        # Screenshot bound to this action's result
        if r.screenshot:
            content.append({
                "type": "text",
                "text": "Current screen after execution:",
            })
            content.append({
                "type": "image_b64",
                "data": r.screenshot,
            })

    return {"role": "tool_result", "content": content}


# ── Perceptual Diff ──────────────────────────────────────────────────────────

def screenshot_hash(b64_data: str) -> str:
    """SHA-256 hash of screenshot data (first 16 hex chars)."""
    return hashlib.sha256(b64_data.encode()).hexdigest()[:16]


def perceptual_diff(before_b64: str, after_b64: str) -> float:
    """Compute perceptual difference between two screenshots.

    Returns 0.0 (identical) to 1.0 (completely different).
    Uses pixel-level mean squared error on downsampled images.
    Falls back to hash comparison if PIL not available.
    """
    if before_b64 == after_b64:
        return 0.0

    try:
        from PIL import Image
        import io

        before_img = Image.open(io.BytesIO(base64.b64decode(before_b64)))
        after_img = Image.open(io.BytesIO(base64.b64decode(after_b64)))

        # Downsample to 64x64 for fast comparison
        size = (64, 64)
        before_small = before_img.resize(size).convert("L")
        after_small = after_img.resize(size).convert("L")

        before_pixels = list(before_small.getdata())
        after_pixels = list(after_small.getdata())

        if len(before_pixels) != len(after_pixels):
            return 1.0

        # Normalized MSE
        mse = sum((a - b) ** 2 for a, b in zip(before_pixels, after_pixels))
        mse /= len(before_pixels) * 255.0 * 255.0
        return min(mse ** 0.5 * 5.0, 1.0)  # scale up for sensitivity

    except ImportError:
        # No PIL — fall back to hash comparison
        return 0.0 if before_b64 == after_b64 else 0.5
    except Exception as e:
        log.warning("perceptual_diff failed: %s", e)
        return 0.5


def crop_screenshot_b64(
    screenshot_b64: str,
    x1: float, y1: float, x2: float, y2: float,
) -> str:
    """Crop a base64 screenshot. Coordinates are percentages (0-100).

    Returns cropped image as base64 JPEG.
    Coordinate system matches KVM mouse operations.
    """
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(base64.b64decode(screenshot_b64)))
    w, h = img.size
    left   = int(w * max(0, min(x1, 100)) / 100)
    top    = int(h * max(0, min(y1, 100)) / 100)
    right  = int(w * max(0, min(x2, 100)) / 100)
    bottom = int(h * max(0, min(y2, 100)) / 100)
    if left >= right or top >= bottom:
        raise ValueError(f"Invalid crop region: ({x1},{y1})-({x2},{y2})")
    cropped = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def classify_change(score: float) -> str:
    """Classify change score into none/minor/major."""
    if score < 0.02:
        return "none"
    if score < 0.15:
        return "minor"
    return "major"


# ── Tool Definitions (Portable Format) ───────────────────────────────────────

INNERCLAW_TOOLS: list[dict] = [
    {
        "name": "type_text",
        "description": "Type ASCII text on the remote computer. CJK characters are NOT supported via KVM HID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "ASCII text to type (max 500 chars)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "key_tap",
        "description": "Press a single key. Use W3C key names: Enter, Escape, Tab, Backspace, Space, Delete, ArrowUp/Down/Left/Right, F1-F12, KeyA-KeyZ, Digit0-Digit9.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "W3C key name"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "key_combo",
        "description": "Press a key combination simultaneously (e.g. Ctrl+C, Alt+Tab, Ctrl+Alt+Delete).",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "W3C key names to press simultaneously",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "mouse_click",
        "description": "Click at a screen position. Coordinates are percentages (0-100). (0,0)=top-left, (100,100)=bottom-right.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X percentage (0-100)"},
                "y": {"type": "number", "description": "Y percentage (0-100)"},
                "button": {"type": "string", "enum": ["left", "right"], "description": "Mouse button (default: left)"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "mouse_double",
        "description": "Double-click at a screen position. Coordinates are percentages (0-100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X percentage (0-100)"},
                "y": {"type": "number", "description": "Y percentage (0-100)"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the screen. Negative=up, positive=down.",
        "input_schema": {
            "type": "object",
            "properties": {
                "delta_y": {"type": "integer", "description": "Scroll amount (negative=up, positive=down)"},
            },
            "required": ["delta_y"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for a slow operation to complete (page load, command execution). Hard limit: 10 seconds. NEVER use wait in a loop for periodic monitoring — use create_task instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Seconds to wait (max 10)"},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a scheduled monitoring task on the KVM management device. Choose from predefined task types — arbitrary shell commands are NOT allowed. Use this for ANY periodic/scheduled/cron-like request instead of installing cron or systemd timers on the remote machine.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Task display name (e.g. 'CPU Monitor')"},
                "task_type": {
                    "type": "string",
                    "enum": ["check_cpu", "check_memory", "check_disk", "check_temp",
                             "check_uptime", "check_network", "check_services", "ping"],
                    "description": "Predefined monitoring task type",
                },
                "interval_minutes": {"type": "integer", "description": "Run every N minutes (minimum 1)"},
                "args": {"type": "object", "description": "Optional task-specific args, e.g. {\"target\": \"8.8.8.8\"} for ping"},
            },
            "required": ["name", "task_type", "interval_minutes"],
        },
    },
]
