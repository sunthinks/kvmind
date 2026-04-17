"""Tests for myclaw_gateway.py — action level check, error classes, offline fallback."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from lib.myclaw_gateway import (
    MyClawRateLimitError,
    MyClawForbiddenError,
    MyClawOfflineError,
    MyClawGateway,
    StartResult,
    SignedActions,
    ACTION_LEVELS,
)


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------

class TestMyClawErrors:
    def test_rate_limit_error_attrs(self):
        err = MyClawRateLimitError(retry_after=30, usage_count=5, usage_limit=5)
        assert err.retry_after == 30
        assert err.usage_count == 5
        assert err.usage_limit == 5
        assert "30" in str(err)

    def test_rate_limit_error_defaults(self):
        err = MyClawRateLimitError()
        assert err.retry_after == 0
        assert err.usage_count == 0
        assert err.usage_limit == 0

    def test_forbidden_error_code(self):
        err = MyClawForbiddenError(code="schedule_not_allowed")
        assert err.code == "schedule_not_allowed"
        assert "schedule_not_allowed" in str(err)

    def test_forbidden_error_default(self):
        err = MyClawForbiddenError()
        assert err.code == ""

    def test_offline_error(self):
        err = MyClawOfflineError("connection refused")
        assert "connection refused" in str(err)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_start_result_defaults(self):
        r = StartResult(session_id="s1", prompt="hello")
        assert r.session_id == "s1"
        assert r.prompt == "hello"
        assert r.policy == {}

    def test_start_result_with_policy(self):
        r = StartResult(session_id="s1", prompt="p", policy={"max_steps": 60})
        assert r.policy["max_steps"] == 60

    def test_signed_actions(self):
        sa = SignedActions(
            actions=[{"name": "mouse_click", "args": {"x": 50, "y": 50}}],
            signature="ed25519:abc",
            timestamp=1000,
            nonce="n1",
        )
        assert len(sa.actions) == 1
        assert sa.signature == "ed25519:abc"
        assert sa.timestamp == 1000
        assert sa.nonce == "n1"


# ---------------------------------------------------------------------------
# ACTION_LEVELS mapping
# ---------------------------------------------------------------------------

class TestActionLevels:
    def test_l1_actions(self):
        l1_names = ["mouse_click", "mouse_double", "mouse_move", "scroll", "type_text", "wait", "done", "key_tap"]
        for name in l1_names:
            assert ACTION_LEVELS[name] == 1, f"{name} should be L1"

    def test_l2_actions(self):
        for name in ["key_combo"]:
            assert ACTION_LEVELS[name] == 2, f"{name} should be L2"

    def test_l3_actions(self):
        assert ACTION_LEVELS["power"] == 3


# ---------------------------------------------------------------------------
# check_action_level (static method, no IO)
# ---------------------------------------------------------------------------

class TestCheckActionLevel:
    def test_all_l1_within_l1(self):
        actions = [
            {"name": "mouse_click", "args": {"x": 50, "y": 50}},
            {"name": "type_text", "args": {"text": "hello"}},
            {"name": "wait", "args": {"seconds": 1}},
        ]
        assert MyClawGateway.check_action_level(actions, max_level=1) is None

    def test_l2_action_rejected_at_l1(self):
        actions = [
            {"name": "mouse_click", "args": {"x": 50, "y": 50}},
            {"name": "key_combo", "args": {"keys": ["ctrl", "c"]}},
        ]
        err = MyClawGateway.check_action_level(actions, max_level=1)
        assert err is not None
        assert "key_combo" in err
        assert "level 2" in err

    def test_l2_action_ok_at_l2(self):
        actions = [{"name": "key_tap", "args": {"key": "enter"}}]
        assert MyClawGateway.check_action_level(actions, max_level=2) is None

    def test_power_rejected_at_l2(self):
        actions = [{"name": "power", "args": {"action": "reboot"}}]
        err = MyClawGateway.check_action_level(actions, max_level=2)
        assert err is not None
        assert "power" in err
        assert "level 3" in err

    def test_power_ok_at_l3(self):
        actions = [{"name": "power", "args": {"action": "off"}}]
        assert MyClawGateway.check_action_level(actions, max_level=3) is None

    def test_unknown_action_passes(self):
        """Unknown actions not in ACTION_LEVELS should not be blocked by level check."""
        actions = [{"name": "some_future_action", "args": {}}]
        assert MyClawGateway.check_action_level(actions, max_level=1) is None

    def test_empty_actions(self):
        assert MyClawGateway.check_action_level([], max_level=1) is None

    def test_mixed_levels_blocked_by_highest(self):
        actions = [
            {"name": "mouse_click", "args": {"x": 10, "y": 10}},
            {"name": "key_tap", "args": {"key": "a"}},
            {"name": "power", "args": {"action": "reboot"}},
        ]
        err = MyClawGateway.check_action_level(actions, max_level=2)
        assert err is not None
        assert "power" in err


# ---------------------------------------------------------------------------
# Offline behavior: cloud unreachable = same as no subscription (local AI only)
# _offline_fallback was removed — start_session returns None on network error.
# ---------------------------------------------------------------------------
