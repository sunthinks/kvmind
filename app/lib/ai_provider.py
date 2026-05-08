"""
AI Provider Abstraction Layer for KVMind

Two provider backends share one portable message format:

  OpenAIProvider  – OpenAI-compatible /chat/completions (Gemini, OpenAI, local)
  AnthropicProvider – Anthropic native /messages (Claude)

Portable message format:
  - Text:        {"type": "text", "text": "..."}
  - Image:       {"type": "image_b64", "data": "..."}
  - Tool use:    {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
  - Tool result: {"type": "tool_result", "tool_use_id": "...", "content": "..."}

Each provider transforms these into its native wire format inside send().
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import aiohttp

log = logging.getLogger(__name__)


# ── Shared HTTP session (audit-r4 R4-CQ-04) ────────────────────────────────
#
# Previously every outbound LLM call did `async with aiohttp.ClientSession():
# async with session.post(...)`. That forced a new TCP + TLS handshake for
# every request. On Anthropic/OpenAI with HTTP/2 keep-alive this is wasteful
# (100–300ms added latency per call on high-RTT links).
#
# We now hold a lazy module-level ClientSession. The runtime is single-event-
# loop and single-process, so one shared session is correct. The session is
# created on first use inside the running event loop (can't be built at
# import time because no loop exists yet) and closed explicitly from
# runtime shutdown via `close_shared_session()`.
_shared_session: Optional[aiohttp.ClientSession] = None
_shared_session_lock: Optional[asyncio.Lock] = None


async def _get_shared_session() -> aiohttp.ClientSession:
    global _shared_session, _shared_session_lock
    if _shared_session is not None and not _shared_session.closed:
        return _shared_session
    if _shared_session_lock is None:
        _shared_session_lock = asyncio.Lock()
    async with _shared_session_lock:
        if _shared_session is None or _shared_session.closed:
            # per-host connection pool; keep-alive honors server directives
            connector = aiohttp.TCPConnector(limit=20, limit_per_host=8)
            _shared_session = aiohttp.ClientSession(connector=connector)
    return _shared_session


async def close_shared_session() -> None:
    """Close the shared HTTP session. Called from runtime shutdown."""
    global _shared_session
    if _shared_session is not None and not _shared_session.closed:
        await _shared_session.close()
    _shared_session = None


# ── Structured Response ─────────────────────────────────────────────────────

@dataclass
class ProviderResponse:
    """Structured response from any AI provider."""
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    # Each tool_call: {"id": "...", "name": "...", "args": {...}}
    stop_reason: str = ""  # "end_turn"/"tool_use"/"stop"/"max_tokens"

    def has_embedded_tool_json(self, tool_names: set[str]) -> bool:
        """True if text contains tool calls as JSON instead of native API.

        Used by model_router to detect models that don't support function calling.
        Checks for known tool names AND shorthand patterns.
        """
        if not self.text:
            return False
        return _has_tool_json_shortcuts(self.text, tool_names)

    def to_history_message(self) -> dict:
        """Build portable assistant message for conversation history."""
        if not self.tool_calls:
            return {"role": "assistant", "content": self.text}
        content: list[dict] = []
        if self.text:
            content.append({"type": "text", "text": self.text})
        for tc in self.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["args"],
            })
        return {"role": "assistant", "content": content}


# ── Tool JSON noise detection ──────────────────────────────────────────────

_MAX_TOOL_JSON_CHARS = 1000
_TOOL_PARAM_TOOLS = {
    "text": "type_text",
    "key": "key_tap",
    "keys": "key_combo",
    "delta_y": "scroll",
    "seconds": "wait",
}
_KNOWN_TEXT_TOOL_NAMES = set(_TOOL_PARAM_TOOLS.values()) | {
    "mouse_click",
    "mouse_double",
    "mouse_move",
    "scroll",
    "wait",
    "create_task",
    "power",
}


def _tool_names_match(name: str, tool_names: set[str] | None) -> bool:
    """Return True if a text tool name is relevant for this request."""
    if tool_names:
        return name in tool_names
    return name in _KNOWN_TEXT_TOOL_NAMES


def _is_tool_json_object(obj: object, tool_names: set[str] | None = None) -> bool:
    """True if a parsed JSON value looks like a tool call, not ordinary text."""
    if isinstance(obj, list):
        return any(_is_tool_json_object(item, tool_names) for item in obj)
    if not isinstance(obj, dict):
        return False

    name = obj.get("name")
    if isinstance(name, str) and _tool_names_match(name, tool_names):
        return True

    for param, tool_name in _TOOL_PARAM_TOOLS.items():
        if param in obj and _tool_names_match(tool_name, tool_names):
            return True

    if "x" in obj and "y" in obj:
        mouse_tools = {"mouse_click", "mouse_double", "mouse_move"}
        if not tool_names or mouse_tools.intersection(tool_names):
            return True

    return False


def _iter_json_object_candidates(text: str) -> list[tuple[int, int]]:
    """Find balanced JSON object spans in free text, including nested objects."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                spans.append((start, index + 1))
                start = None

        if start is not None and index - start > _MAX_TOOL_JSON_CHARS:
            start = None
            depth = 0
            in_string = False
            escaped = False

    return spans


def _iter_tool_json_spans(text: str, tool_names: set[str] | None = None) -> list[tuple[int, int]]:
    """Return spans for embedded JSON snippets that look like tool calls."""
    spans: list[tuple[int, int]] = []
    stripped = text.strip()
    leading_ws = len(text) - len(text.lstrip())

    if stripped and stripped[0] in "{[" and stripped[-1] in "}]":
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if _is_tool_json_object(parsed, tool_names):
            spans.append((leading_ws, leading_ws + len(stripped)))
            return spans

    for start, end in _iter_json_object_candidates(text):
        try:
            parsed = json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
        if _is_tool_json_object(parsed, tool_names):
            spans.append((start, end))

    return spans


def _has_tool_json_shortcuts(text: str, tool_names: set[str] | None = None) -> bool:
    """True if text contains JSON that looks like a tool call."""
    return bool(_iter_tool_json_spans(text, tool_names))


def is_tool_noise(text: str) -> bool:
    """True if assistant text is mostly embedded tool JSON noise."""
    spans = _iter_tool_json_spans(text)
    if not spans:
        return False

    residue = text
    for start, end in reversed(spans):
        residue = residue[:start] + residue[end:]
    residue = re.sub(r"[\s`.,:;，。；：、-]+", "", residue)
    return not residue or (len(text.strip()) < 300 and len(residue) < 40)


# ── Exceptions ───────────────────────────────────────────────────────────────

class ProviderError(Exception):
    """Raised when an AI provider request fails."""


# ── Provider Protocol ────────────────────────────────────────────────────────

@runtime_checkable
class AIProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def default_model(self) -> str: ...

    async def send(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
        timeout: float = 60.0,
        tools: List[Dict[str, Any]] | None = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse: ...


# ── OpenAI wire format ───────────────────────────────────────────────────────

def _build_openai_content(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert portable content parts to OpenAI content blocks."""
    out: List[Dict[str, Any]] = []
    for p in parts:
        if p["type"] == "text":
            out.append({"type": "text", "text": p["text"]})
        elif p["type"] == "image_b64":
            out.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{p['data']}",
                    "detail": "high",
                },
            })
    return out


def _build_openai_messages(
    system_prompt: str,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert portable messages to OpenAI wire format."""
    wire: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "tool_result":
            # Split into individual tool messages + optional screenshot user message
            screenshot_parts: list[dict] = []
            for part in content:
                if part["type"] == "tool_result":
                    rc = part.get("content", "")
                    text = rc if isinstance(rc, str) else " ".join(
                        p.get("text", "") for p in rc if p["type"] == "text"
                    )
                    wire.append({
                        "role": "tool",
                        "tool_call_id": part["tool_use_id"],
                        "content": text or "OK",
                    })
                elif part["type"] in ("text", "image_b64"):
                    screenshot_parts.append(part)
            if screenshot_parts:
                wire.append({
                    "role": "user",
                    "content": _build_openai_content(screenshot_parts),
                })

        elif role == "assistant" and isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for part in content:
                if part["type"] == "text":
                    text_parts.append(part["text"])
                elif part["type"] == "tool_use":
                    tool_calls.append({
                        "id": part["id"],
                        "type": "function",
                        "function": {
                            "name": part["name"],
                            "arguments": json.dumps(part["input"]),
                        },
                    })
            msg_dict: Dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) or None,
            }
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            wire.append(msg_dict)

        elif isinstance(content, str):
            wire.append({"role": role, "content": content})
        else:
            wire.append({
                "role": role,
                "content": _build_openai_content(content),
            })

    return wire


def _to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert portable tool definitions to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object"}),
            },
        }
        for t in tools
    ]


# ── Thinking / reasoning content stripping ──────────────────────────────────
#
# Reasoning models (DeepSeek-R1, Qwen3, 通义, Kimi-thinking, Claude extended
# thinking 等) emit internal reasoning that should not reach the user. The tag
# names vary widely and prefix injection often eats the opening tag, leaving
# only a bare closing tag. The strip rules must cover all of:
#
#   <think>...</think>            paired XML
#   <thinking>...</thinking>      paired (alternative name)
#   <|thinking|>...<|/thinking|>  special token style
#   ...</think>final answer       prefix-injection bare close
#   <think>truncated EOF          model output cut mid-thought
#
# Tag name vocabulary is configurable from kdcms (POST /api/myclaw/start
# response_format.thinking_tags) so that prompt-and-strip-rules stay in sync
# without device OTA. _DEFAULT_THINKING_TAGS is the fallback when cloud config
# is absent (older kdcms or first-boot).

_DEFAULT_THINKING_TAGS: List[str] = [
    "think", "thinking", "reasoning", "reason",
    "scratchpad", "scratch",
    "analysis", "analyse", "analyze",
    "plan", "planning",
    "reflection", "reflect",
    "monologue", "inner_monologue", "inner-monologue",
    "observation",
    "thought", "thoughts",
    "deliberation", "draft", "cot",
    "思考", "推理", "分析", "计划", "反思", "草稿", "内心独白",
]

# Bare-close detector for tags OUTSIDE the configured vocabulary — log warning
# only (do not strip) so ops can extend the kdcms config when new tags appear.
_UNKNOWN_BARE_CLOSE_RE = re.compile(
    r"\A.{0,2048}?<\s*/\s*([A-Za-z_一-鿿][\w\-一-鿿]{1,32})\s*>",
    re.DOTALL,
)


def _build_strip_patterns(tag_names: List[str]) -> Optional[Dict[str, List[re.Pattern]]]:
    """Compile strip regex set covering XML and special-token syntax."""
    if not tag_names:
        return None
    alt = "|".join(re.escape(name) for name in tag_names)
    return {
        "paired": [
            re.compile(rf"<\s*({alt})\s*>.*?<\s*/\s*\1\s*>\s*", re.DOTALL | re.IGNORECASE),
            re.compile(rf"<\|\s*({alt})\s*\|>.*?<\|\s*/\s*\1\s*\|>\s*", re.DOTALL | re.IGNORECASE),
        ],
        "bare_close": [
            re.compile(rf"\A.*?<\s*/\s*({alt})\s*>\s*", re.DOTALL | re.IGNORECASE),
            re.compile(rf"\A.*?<\|\s*/\s*({alt})\s*\|>\s*", re.DOTALL | re.IGNORECASE),
        ],
        "bare_open": [
            re.compile(rf"<\s*({alt})\s*>.*\Z", re.DOTALL | re.IGNORECASE),
            re.compile(rf"<\|\s*({alt})\s*\|>.*\Z", re.DOTALL | re.IGNORECASE),
        ],
        "any_open": [
            re.compile(rf"<\s*({alt})\s*>", re.IGNORECASE),
            re.compile(rf"<\|\s*({alt})\s*\|>", re.IGNORECASE),
        ],
    }


def _strip_think_tags(text: str, response_format: Optional[Dict[str, Any]] = None) -> str:
    """Strip thinking / reasoning blocks. Vocab from cloud config, fallback to defaults."""
    if not text:
        return text

    rf = response_format or {}
    tag_names = rf.get("thinking_tags") or _DEFAULT_THINKING_TAGS
    strict_bare_close = rf.get("strict_bare_close", True)
    max_prefix = rf.get("max_strip_prefix_bytes", 2048)

    patterns = _build_strip_patterns(tag_names)
    if not patterns:
        return text.strip()

    for p in patterns["paired"]:
        text = p.sub("", text)

    if strict_bare_close:
        has_open = any(p.search(text) for p in patterns["any_open"])
        if not has_open:
            for p in patterns["bare_close"]:
                m = p.search(text)
                if m and m.end() <= max_prefix:
                    text = text[m.end():]
                    break

    for p in patterns["bare_open"]:
        text = p.sub("", text)

    m = _UNKNOWN_BARE_CLOSE_RE.search(text)
    if m and m.group(1).lower() not in {n.lower() for n in tag_names}:
        log.warning(
            "ai_provider.unknown_bare_close_tag tag=%r — consider adding to kdcms response_format.thinking_tags",
            m.group(1),
        )

    return text.strip()


def _parse_openai_response(
    data: dict,
    response_format: Optional[Dict[str, Any]] = None,
) -> ProviderResponse:
    """Parse OpenAI /chat/completions response.

    Field whitelist — only `content` is consumed. Reasoning-only fields like
    `reasoning_content` (DeepSeek-R1, Qwen3, 通义) and `reasoning` (OpenAI o1)
    are intentionally ignored: they carry the model's private chain-of-thought,
    not the answer.
    """
    choice = data["choices"][0]
    msg = choice["message"]
    text = msg.get("content", "") or ""
    stop = choice.get("finish_reason", "")

    text = _strip_think_tags(text, response_format)

    tool_calls: list[dict] = []
    for tc in msg.get("tool_calls", []):
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}
        tool_calls.append({
            "id": tc["id"],
            "name": tc["function"]["name"],
            "args": args,
        })

    return ProviderResponse(text=text, tool_calls=tool_calls, stop_reason=stop)


# ── Anthropic wire format ────────────────────────────────────────────────────

def _build_anthropic_content(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert portable content parts to Anthropic content blocks."""
    out: List[Dict[str, Any]] = []
    for p in parts:
        if p["type"] == "text":
            out.append({"type": "text", "text": p["text"]})
        elif p["type"] == "image_b64":
            out.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": p["data"],
                },
            })
    return out


def _build_anthropic_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert portable messages to Anthropic wire format."""
    wire: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "tool_result":
            # All parts in a single user message (Anthropic requirement)
            blocks: List[Dict[str, Any]] = []
            for part in content:
                if part["type"] == "tool_result":
                    rc = part.get("content", "")
                    if isinstance(rc, list):
                        blocks.append({
                            "type": "tool_result",
                            "tool_use_id": part["tool_use_id"],
                            "content": _build_anthropic_content(rc),
                        })
                    else:
                        blocks.append({
                            "type": "tool_result",
                            "tool_use_id": part["tool_use_id"],
                            "content": str(rc),
                        })
                elif part["type"] == "text":
                    blocks.append({"type": "text", "text": part["text"]})
                elif part["type"] == "image_b64":
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": part["data"],
                        },
                    })
            wire.append({"role": "user", "content": blocks})

        elif role == "assistant" and isinstance(content, list):
            blocks = []
            for part in content:
                if part["type"] == "text":
                    blocks.append({"type": "text", "text": part["text"]})
                elif part["type"] == "tool_use":
                    blocks.append({
                        "type": "tool_use",
                        "id": part["id"],
                        "name": part["name"],
                        "input": part["input"],
                    })
            wire.append({"role": "assistant", "content": blocks})

        elif isinstance(content, str):
            wire.append({"role": role, "content": content})
        else:
            wire.append({
                "role": role,
                "content": _build_anthropic_content(content),
            })

    return wire


_KNOWN_ANTHROPIC_BLOCK_TYPES = {"text", "tool_use", "thinking", "redacted_thinking"}


def _parse_anthropic_response(
    data: dict,
    response_format: Optional[Dict[str, Any]] = None,
) -> ProviderResponse:
    """Parse Anthropic /messages response.

    Block-type whitelist — only `text` and `tool_use` reach the user. Extended
    thinking blocks (`thinking` / `redacted_thinking`) are dropped silently.
    Unknown future types log a warning and are dropped (forward-compat).
    """
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in data.get("content", []):
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "name": block["name"],
                "args": block.get("input", {}),
            })
        elif btype in _KNOWN_ANTHROPIC_BLOCK_TYPES:
            pass  # thinking / redacted_thinking — silent drop
        else:
            log.warning("ai_provider.unknown_anthropic_block_type type=%r", btype)

    text = _strip_think_tags("\n".join(text_parts), response_format)
    return ProviderResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason=data.get("stop_reason", ""),
    )


# ── OpenAI-Compatible Provider ───────────────────────────────────────────────

class OpenAIProvider:
    """POST {base_url}/chat/completions — works with Gemini, OpenAI, local."""

    def __init__(self, base_url: str, api_key: str, default_model: str) -> None:
        if not default_model:
            raise ValueError(
                "OpenAIProvider requires an explicit default_model — "
                "device code no longer maintains a model catalog. "
                "Pick a model in MyClaw settings before instantiating."
            )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return self._default_model

    async def send(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
        timeout: float = 60.0,
        tools: List[Dict[str, Any]] | None = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        wire_messages = _build_openai_messages(system_prompt, messages)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": wire_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = _to_openai_tools(tools)

        url = f"{self._base_url}/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key and self._api_key not in ("none", "no-key-required"):
            headers["Authorization"] = f"Bearer {self._api_key}"

        use_ssl = url.startswith("https://")

        log.debug("OpenAI request -> %s  model=%s  tools=%s  ssl=%s",
                   url, model, bool(tools), use_ssl)
        try:
            session = await _get_shared_session()
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=use_ssl if use_ssl else False,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise ProviderError(
                        f"OpenAI API {resp.status}: {body[:500]}"
                    )
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        response = _parse_openai_response(data, response_format)
        log.debug("OpenAI response: %d chars, %d tool_calls",
                   len(response.text), len(response.tool_calls))
        return response


# ── Anthropic Native Provider ────────────────────────────────────────────────

class AnthropicProvider:
    """POST {base_url}/messages — native Anthropic API for Claude."""

    def __init__(self, base_url: str, api_key: str, default_model: str) -> None:
        if not default_model:
            raise ValueError(
                "AnthropicProvider requires an explicit default_model — "
                "device code no longer maintains a model catalog. "
                "Pick a model in MyClaw settings before instantiating."
            )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def default_model(self) -> str:
        return self._default_model

    async def send(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
        timeout: float = 60.0,
        tools: List[Dict[str, Any]] | None = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        wire_messages = _build_anthropic_messages(messages)

        payload: Dict[str, Any] = {
            "model": model,
            "system": system_prompt,
            "messages": wire_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            # Anthropic native format matches our portable format
            payload["tools"] = tools

        url = f"{self._base_url}/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        log.debug("Anthropic request -> %s  model=%s  tools=%s",
                   url, model, bool(tools))
        try:
            session = await _get_shared_session()
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=True,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise ProviderError(
                        f"Anthropic API {resp.status}: {body[:500]}"
                    )
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        response = _parse_anthropic_response(data, response_format)
        log.debug("Anthropic response: %d chars, %d tool_calls",
                   len(response.text), len(response.tool_calls))
        return response
