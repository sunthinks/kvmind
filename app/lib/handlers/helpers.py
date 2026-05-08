"""Shared utilities for handler modules."""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from ..kvmind_client import ai_error_message


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        body=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json",
        status=status,
    )


def ai_error_response(code: str, lang: str = "en", status: int = 502) -> web.Response:
    """Unified AI-failure response body: {error: {code, message}}.

    `code` is a stable string the frontend can branch on; `message` is a
    lang-localized human-readable fallback.
    """
    return json_response(
        {"error": {"code": code, "message": ai_error_message(code, lang)}},
        status=status,
    )


__all__ = ["json_response", "ai_error_message", "ai_error_response"]
