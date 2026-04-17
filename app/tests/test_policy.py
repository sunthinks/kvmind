"""Tests for innerclaw/policy.py — Execution policy (dedup, loop, stale detection)."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
from unittest.mock import patch, MagicMock

import pytest

from lib.innerclaw.policy import ExecutionPolicy
from lib.innerclaw.tools import Action
from lib.innerclaw.budget import Budget


@pytest.fixture
def policy():
    return ExecutionPolicy()


@pytest.fixture
def budget():
    b = Budget(max_actions=60, max_ai_calls=30, timeout_seconds=300)
    b.start()
    return b


def make_action(name: str = "type_text", input: dict = None) -> Action:
    return Action(id=f"tool_{name}", name=name, input=input or {"text": "x"})


# ── optimize: consecutive dedup ─────────────────────────────────────────────

class TestOptimizeConsecutiveDedup:
    def test_empty_actions(self, policy):
        assert policy.optimize([]) == []

    def test_single_action(self, policy):
        actions = [make_action()]
        assert policy.optimize(actions) == actions

    def test_removes_consecutive_duplicates(self, policy):
        a = make_action("type_text", {"text": "hello"})
        b = make_action("type_text", {"text": "hello"})
        c = make_action("key_tap", {"key": "Enter"})

        result = policy.optimize([a, b, c])
        assert len(result) == 2
        assert result[0].name == "type_text"
        assert result[1].name == "key_tap"

    def test_keeps_non_consecutive_same_actions(self, policy):
        a = make_action("type_text", {"text": "a"})
        b = make_action("key_tap", {"key": "Enter"})
        c = make_action("type_text", {"text": "a"})

        result = policy.optimize([a, b, c])
        assert len(result) == 3

    def test_removes_triple_consecutive(self, policy):
        a1 = make_action("key_tap", {"key": "Enter"})
        a2 = make_action("key_tap", {"key": "Enter"})
        a3 = make_action("key_tap", {"key": "Enter"})

        result = policy.optimize([a1, a2, a3])
        assert len(result) == 1


# ── optimize: group pattern dedup ───────────────────────────────────────────

class TestOptimizeGroupDedup:
    def test_abab_pattern(self, policy):
        a = make_action("type_text", {"text": "a"})
        b = make_action("key_tap", {"key": "Enter"})
        a2 = make_action("type_text", {"text": "a"})
        b2 = make_action("key_tap", {"key": "Enter"})

        result = policy.optimize([a, b, a2, b2])
        assert len(result) == 2
        assert result[0].name == "type_text"
        assert result[1].name == "key_tap"

    def test_abcabc_pattern(self, policy):
        actions = [
            make_action("type_text", {"text": "x"}),
            make_action("key_tap", {"key": "Tab"}),
            make_action("type_text", {"text": "y"}),
            make_action("type_text", {"text": "x"}),
            make_action("key_tap", {"key": "Tab"}),
            make_action("type_text", {"text": "y"}),
        ]
        result = policy.optimize(actions)
        assert len(result) == 3

    def test_no_pattern_keeps_all(self, policy):
        actions = [
            make_action("type_text", {"text": "a"}),
            make_action("key_tap", {"key": "Enter"}),
            make_action("mouse_click", {"x": 10, "y": 20}),
            make_action("type_text", {"text": "b"}),
        ]
        result = policy.optimize(actions)
        assert len(result) == 4


# ── should_abort: budget ────────────────────────────────────────────────────

class TestShouldAbortBudget:
    def test_within_budget(self, policy, budget):
        actions = [make_action()]
        assert policy.should_abort([], actions, budget) is None

    def test_actions_exhausted(self, policy):
        budget = Budget(max_actions=0, max_ai_calls=30, timeout_seconds=300)
        budget.start()
        reason = policy.should_abort([], [make_action()], budget)
        assert reason is not None
        assert "Max actions" in reason

    def test_ai_calls_exhausted(self, policy):
        budget = Budget(max_actions=60, max_ai_calls=0, timeout_seconds=300)
        budget.start()
        reason = policy.should_abort([], [make_action()], budget)
        assert reason is not None
        assert "Max AI calls" in reason

    def test_timeout(self, policy):
        budget = Budget(max_actions=60, max_ai_calls=30, timeout_seconds=0.01)
        budget.start()
        time.sleep(0.02)  # exceed timeout
        reason = policy.should_abort([], [make_action()], budget)
        assert reason is not None
        assert "Timeout" in reason


# ── should_abort: loop detection ────────────────────────────────────────────

class TestShouldAbortLoop:
    def test_no_loop_with_different_actions(self, policy, budget):
        for i in range(5):
            actions = [make_action("type_text", {"text": f"msg{i}"})]
            reason = policy.should_abort([], actions, budget)
        assert reason is None

    def test_detects_loop_after_max_consecutive(self, policy, budget):
        same_action = [make_action("type_text", {"text": "stuck"})]
        reason = None
        for _ in range(policy.MAX_CONSECUTIVE_SAME + 1):
            reason = policy.should_abort([], same_action, budget)
        assert reason is not None
        assert "Loop detected" in reason

    def test_loop_resets_on_different_action(self, policy, budget):
        same = [make_action("type_text", {"text": "stuck"})]
        for _ in range(policy.MAX_CONSECUTIVE_SAME - 1):
            policy.should_abort([], same, budget)
        # Different action breaks the streak
        different = [make_action("key_tap", {"key": "Enter"})]
        policy.should_abort([], different, budget)
        # Resume same action — counter should restart
        reason = policy.should_abort([], same, budget)
        assert reason is None


# ── record_change: stale detection ──────────────────────────────────────────

class TestRecordChange:
    def test_none_increments_stale(self, policy):
        for _ in range(policy.MAX_STALE_TURNS - 1):
            assert policy.record_change("none") is None
        reason = policy.record_change("none")
        assert reason is not None
        assert "unchanged" in reason

    def test_minor_resets_stale(self, policy):
        policy.record_change("none")
        policy.record_change("none")
        assert policy.record_change("minor") is None
        # Counter should be reset
        assert policy._stale_count == 0

    def test_major_resets_stale(self, policy):
        policy.record_change("none")
        assert policy.record_change("major") is None
        assert policy._stale_count == 0


# ── reset ───────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_state(self, policy, budget):
        same = [make_action("type_text", {"text": "x"})]
        for _ in range(2):
            policy.should_abort([], same, budget)
        policy.record_change("none")

        policy.reset()

        assert policy._stale_count == 0
        assert len(policy._recent_action_sigs) == 0
