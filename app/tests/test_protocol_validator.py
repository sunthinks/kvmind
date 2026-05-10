"""Tests for InnerClaw protocol self-correction behavior."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.innerclaw.protocol import ProtocolValidator


def test_text_only_first_auto_turn_gets_one_tool_call_nudge():
    proto = ProtocolValidator({"type_text", "key_tap"})

    first = proto.handle_text_only(1)
    second = proto.handle_text_only(2)

    assert first is not None
    assert "use tool_calls now" in first["content"]
    assert second is None
