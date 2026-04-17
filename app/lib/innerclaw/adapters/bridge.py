"""
InnerClaw Adapters — Web/WebSocket Bridge Adapter

Maps RunnerEvents to the frontend WebSocket protocol expected by
myclaw-gateway.js. This is the primary adapter for the KVMind web UI.

Frontend expects:
  {type: "chunk",   content: "..."}        — streaming text
  {type: "done",    full_response: "..."}  — final message
  {type: "tool_call",   name, id, input}   — action start
  {type: "tool_result", name, output, id}  — action done
  {type: "error",   message: "..."}        — error
  {type: "screenshot",  data: "base64..."}  — screenshot
  {type: "confirm_required", action, args}  — dangerous action confirmation
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from aiohttp import web

from .base import BaseAdapter


class WebBridgeAdapter(BaseAdapter):
    """Adapts RunnerEvents to the myclaw-gateway.js WebSocket protocol."""

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self._ws = ws

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_images(self) -> bool:
        return True

    async def send_event(self, event: dict) -> None:
        """Convert a RunnerEvent dict to frontend protocol and send."""
        if self._ws.closed:
            return

        event_type = event.get("event", "")
        run_id = event.get("run_id")
        messages = self._translate(event_type, event)

        for msg in messages:
            if run_id:
                msg["run_id"] = run_id
            if not self._ws.closed:
                await self._ws.send_json(msg)

    async def receive_message(self) -> str | None:
        """Receive a message from the WebSocket client."""
        try:
            msg = await self._ws.receive()
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                # Standard chat message
                if isinstance(data, dict):
                    return data.get("message") or data.get("content") or msg.data
                return msg.data
            return None
        except Exception:
            return None

    def _translate(self, event_type: str, event: dict) -> list[dict]:
        """Translate RunnerEvent to frontend WebSocket messages."""

        if event_type == "thinking":
            return [{"type": "thinking"}]

        if event_type == "ai_text":
            text = event.get("text", "")
            # Send as chunk only — "done" comes from task_done.
            # This prevents intermediate observations from appearing
            # as separate finalized messages in the chat UI.
            return [{"type": "chunk", "content": text}]

        if event_type == "screenshot":
            return [{"type": "screenshot", "data": event.get("screenshot", "")}]

        if event_type == "action_start":
            return [{
                "type": "tool_call",
                "name": event.get("action", ""),
                "id": uuid.uuid4().hex[:8],
                "input": event.get("args", {}),
            }]

        if event_type == "action_done":
            return [{
                "type": "tool_result",
                "name": event.get("action", ""),
                "output": "ok",
                "id": "",
            }]

        if event_type == "action_error":
            return [{
                "type": "tool_result",
                "name": event.get("action", ""),
                "output": f"error: {event.get('error', '')}",
                "id": "",
            }]

        if event_type == "task_done":
            return [{"type": "done", "full_response": event.get("message", "")}]

        if event_type == "task_error":
            return [{"type": "error", "message": event.get("error", "")}]

        if event_type == "confirm_required":
            return [{
                "type": "confirm_required",
                "action": event.get("action", ""),
                "args": event.get("args", {}),
            }]

        # Unknown event — pass through
        return [{"type": event_type, **{k: v for k, v in event.items() if k != "event"}}]
