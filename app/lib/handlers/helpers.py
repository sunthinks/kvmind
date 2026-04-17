"""Shared utilities for handler modules."""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        body=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json",
        status=status,
    )
