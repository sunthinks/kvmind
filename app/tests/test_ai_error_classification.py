"""Tests for provider error classification used by /api/ai/test."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.handlers.ai_config import _classify_provider_error, _normalize_provider_model


def test_gemini_array_error_invalid_model_is_not_endpoint_not_found():
    body = json.dumps([{
        "error": {
            "code": 404,
            "message": (
                "Publisher Model `publishers/google/models/gemini-old` "
                "was not found or your project does not have access to it."
            ),
            "status": "NOT_FOUND",
        }
    }])

    friendly, code = _classify_provider_error(404, body)

    assert code == "invalid_model"
    assert "模型名无效" in friendly


def test_gemini_array_error_invalid_key_is_not_bad_request():
    body = json.dumps([{
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
            "details": [{
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "API_KEY_INVALID",
                "domain": "googleapis.com",
            }],
        }
    }])

    friendly, code = _classify_provider_error(400, body)

    assert code == "invalid_api_key"
    assert "API Key 无效" in friendly


def test_plain_empty_404_remains_endpoint_not_found():
    friendly, code = _classify_provider_error(404, "")

    assert code == "endpoint_not_found"
    assert "API 路径未找到" in friendly


def test_gemini_native_model_prefix_is_stripped_for_openai_compat():
    assert _normalize_provider_model("gemini", "models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert _normalize_provider_model("gemini", "gemini-2.5-flash") == "gemini-2.5-flash"
