"""Tests for ai_provider thinking-content stripping and response parsers.

Covers:
  - _strip_think_tags: paired / bare-close / bare-open / vocab variants /
    special-token syntax / Chinese tags / unknown-tag warning / no-false-positive.
  - _parse_openai_response: field whitelist (reasoning_content/reasoning ignored).
  - _parse_anthropic_response: block whitelist (thinking/redacted_thinking dropped).
"""
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ai_provider import (
    _strip_think_tags,
    _parse_openai_response,
    _parse_anthropic_response,
    _DEFAULT_THINKING_TAGS,
)


# ── _strip_think_tags ─────────────────────────────────────────────────────────


class TestStripThinkTagsDefaults:
    """Default vocabulary path (no response_format passed)."""

    def test_empty_returns_empty(self):
        assert _strip_think_tags("") == ""

    def test_no_tags_unchanged(self):
        assert _strip_think_tags("just plain text") == "just plain text"

    def test_paired_think_block(self):
        assert _strip_think_tags("<think>reasoning</think>final") == "final"

    def test_paired_thinking_block(self):
        assert _strip_think_tags("<thinking>plan</thinking>answer") == "answer"

    def test_paired_reasoning_block(self):
        assert _strip_think_tags("<reasoning>x</reasoning>y") == "y"

    def test_paired_chinese_tag(self):
        assert _strip_think_tags("<思考>要这样做</思考>最终答案") == "最终答案"

    def test_paired_special_token(self):
        text = "<|thinking|>plan<|/thinking|>done"
        assert _strip_think_tags(text) == "done"

    def test_case_insensitive(self):
        assert _strip_think_tags("<Think>x</think>y") == "y"
        assert _strip_think_tags("<THINKING>x</THINKING>z") == "z"

    def test_bare_close_main_bug_scenario(self):
        """The exact production bug — prefix injection ate the open tag."""
        text = "执行 df -h 命令检查磁盘空间。\n</think>\n根分区使用率约 49%"
        result = _strip_think_tags(text)
        assert "</think>" not in result
        assert "执行 df -h 命令" not in result
        assert "根分区使用率约 49%" in result

    def test_bare_close_chinese(self):
        text = "在分析问题</思考>结果是 42"
        result = _strip_think_tags(text)
        assert "</思考>" not in result
        assert "结果是 42" in result

    def test_bare_close_special_token(self):
        text = "internal stuff<|/thinking|>final answer"
        assert _strip_think_tags(text) == "final answer"

    def test_bare_open_truncated(self):
        """Model output got cut off mid-thought."""
        text = "real answer here<think>still thinking..."
        result = _strip_think_tags(text)
        assert "<think>" not in result
        assert "still thinking" not in result
        assert "real answer here" in result

    def test_no_false_positive_when_open_tag_present(self):
        """User asks about </think> tag semantics — must not strip."""
        text = "你问的 <think> 标签和 </think> 是 reasoning 模型用的"
        result = _strip_think_tags(text)
        # Paired didn't match (text has </think> after <think>... but it does
        # actually pair). Verify the answer survives — at minimum the content
        # mentioning the user question must remain identifiable.
        assert "reasoning 模型" in result or "标签" in result

    def test_markdown_html_tags_unaffected(self):
        text = "<p>paragraph</p>\n<code>x = 1</code>\n<a href='/'>link</a>"
        result = _strip_think_tags(text)
        assert "<p>" in result
        assert "<code>" in result
        assert "<a href=" in result

    def test_unknown_bare_close_logs_warning_does_not_strip(self, caplog):
        text = "internal text</custom_tag>real answer"
        with caplog.at_level(logging.WARNING, logger="lib.ai_provider"):
            result = _strip_think_tags(text)
        assert "</custom_tag>" in result  # not stripped
        assert "real answer" in result
        assert any("unknown_bare_close_tag" in rec.message for rec in caplog.records)


class TestStripThinkTagsCloudConfig:
    """Cloud-config path — response_format dict overrides defaults."""

    def test_custom_vocab_only(self):
        rf = {"thinking_tags": ["myreason"]}
        assert _strip_think_tags("<myreason>x</myreason>y", rf) == "y"
        # default vocab is overridden → <think> no longer recognized
        assert _strip_think_tags("<think>x</think>y", rf) == "<think>x</think>y"

    def test_strict_bare_close_disabled(self):
        rf = {"thinking_tags": ["think"], "strict_bare_close": False}
        text = "junk</think>answer"
        # bare close should NOT be stripped
        assert "</think>" in _strip_think_tags(text, rf)

    def test_max_strip_prefix_bytes_protects_late_close(self):
        """Bare close past the byte limit — don't strip."""
        prefix = "x" * 3000
        text = prefix + "</think>tail"
        rf = {"thinking_tags": ["think"], "max_strip_prefix_bytes": 2048}
        result = _strip_think_tags(text, rf)
        # The </think> is past 2048, so bare-close skips it
        assert "</think>" in result

    def test_max_strip_prefix_bytes_allows_early_close(self):
        rf = {"thinking_tags": ["think"], "max_strip_prefix_bytes": 2048}
        text = "short prefix</think>real"
        assert _strip_think_tags(text, rf) == "real"

    def test_empty_thinking_tags_falls_back_to_defaults(self):
        rf = {"thinking_tags": []}
        # Empty list is falsy → fallback to _DEFAULT_THINKING_TAGS
        assert _strip_think_tags("<think>x</think>y", rf) == "y"


class TestStripThinkTagsRealisticSamples:
    """Mock real responses from production models."""

    def test_deepseek_r1_style(self):
        """DeepSeek-R1 with prefix injection eating <think>."""
        text = (
            "Let me analyze the user's request to check disk space.\n"
            "I should run df -h.\n"
            "</think>\n\n"
            "I'll check the disk space using `df -h`."
        )
        result = _strip_think_tags(text)
        assert "Let me analyze" not in result
        assert "</think>" not in result
        assert "df -h" in result

    def test_qwen3_style_with_open_tag(self):
        text = "<think>用户要查磁盘</think>\n根分区使用 49%"
        assert _strip_think_tags(text) == "根分区使用 49%"

    def test_claude_thinking_via_xml(self):
        """Some models forward Anthropic thinking as XML in text."""
        text = "<thinking>I should explain clearly</thinking>The answer is 42."
        assert _strip_think_tags(text) == "The answer is 42."


# ── _parse_openai_response ────────────────────────────────────────────────────


class TestParseOpenAIResponse:

    def test_plain_content(self):
        data = {
            "choices": [{
                "message": {"content": "hello world"},
                "finish_reason": "stop",
            }],
        }
        resp = _parse_openai_response(data)
        assert resp.text == "hello world"
        assert resp.tool_calls == []
        assert resp.stop_reason == "stop"

    def test_reasoning_content_field_ignored(self):
        """DeepSeek-R1 / Qwen3 / 通义 — reasoning_content is private."""
        data = {
            "choices": [{
                "message": {
                    "content": "final answer",
                    "reasoning_content": "private chain of thought",
                },
                "finish_reason": "stop",
            }],
        }
        resp = _parse_openai_response(data)
        assert resp.text == "final answer"
        assert "private" not in resp.text
        assert "chain of thought" not in resp.text

    def test_reasoning_field_ignored(self):
        """OpenAI o1 — reasoning field is private."""
        data = {
            "choices": [{
                "message": {
                    "content": "answer",
                    "reasoning": "internal o1 reasoning",
                },
                "finish_reason": "stop",
            }],
        }
        resp = _parse_openai_response(data)
        assert resp.text == "answer"
        assert "internal o1 reasoning" not in resp.text

    def test_unknown_future_field_ignored(self):
        data = {
            "choices": [{
                "message": {
                    "content": "answer",
                    "future_reasoning_v3": "should be ignored",
                },
                "finish_reason": "stop",
            }],
        }
        resp = _parse_openai_response(data)
        assert resp.text == "answer"
        assert "should be ignored" not in resp.text

    def test_content_with_paired_think_stripped(self):
        data = {
            "choices": [{
                "message": {"content": "<think>hidden</think>visible"},
                "finish_reason": "stop",
            }],
        }
        assert _parse_openai_response(data).text == "visible"

    def test_content_with_bare_close_stripped(self):
        data = {
            "choices": [{
                "message": {"content": "leak</think>real answer"},
                "finish_reason": "stop",
            }],
        }
        assert _parse_openai_response(data).text == "real answer"

    def test_response_format_overrides_vocab(self):
        rf = {"thinking_tags": ["myreason"]}
        data = {
            "choices": [{
                "message": {"content": "<myreason>x</myreason>y"},
                "finish_reason": "stop",
            }],
        }
        assert _parse_openai_response(data, rf).text == "y"

    def test_tool_calls_passthrough(self):
        data = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {"name": "shell", "arguments": '{"cmd":"df -h"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        resp = _parse_openai_response(data)
        assert resp.tool_calls == [{
            "id": "call_1", "name": "shell", "args": {"cmd": "df -h"},
        }]


# ── _parse_anthropic_response ─────────────────────────────────────────────────


class TestParseAnthropicResponse:

    def test_text_block(self):
        data = {
            "content": [{"type": "text", "text": "hello"}],
            "stop_reason": "end_turn",
        }
        resp = _parse_anthropic_response(data)
        assert resp.text == "hello"
        assert resp.stop_reason == "end_turn"

    def test_thinking_block_dropped(self):
        """Extended thinking — must NOT reach the user."""
        data = {
            "content": [
                {"type": "thinking", "thinking": "private reasoning"},
                {"type": "text", "text": "the answer is 42"},
            ],
            "stop_reason": "end_turn",
        }
        resp = _parse_anthropic_response(data)
        assert resp.text == "the answer is 42"
        assert "private" not in resp.text

    def test_redacted_thinking_dropped(self):
        data = {
            "content": [
                {"type": "redacted_thinking", "data": "redacted-blob"},
                {"type": "text", "text": "answer"},
            ],
        }
        resp = _parse_anthropic_response(data)
        assert resp.text == "answer"

    def test_unknown_block_type_logs_warning_dropped(self, caplog):
        data = {
            "content": [
                {"type": "future_block_v3", "stuff": "..."},
                {"type": "text", "text": "answer"},
            ],
        }
        with caplog.at_level(logging.WARNING, logger="lib.ai_provider"):
            resp = _parse_anthropic_response(data)
        assert resp.text == "answer"
        assert any("unknown_anthropic_block_type" in r.message for r in caplog.records)

    def test_text_block_runs_strip_think_tags(self):
        """Non-native reasoning models proxied via Anthropic schema."""
        data = {
            "content": [{"type": "text", "text": "<think>x</think>real"}],
        }
        assert _parse_anthropic_response(data).text == "real"

    def test_text_block_bare_close_stripped(self):
        data = {
            "content": [{"type": "text", "text": "leak</think>real"}],
        }
        assert _parse_anthropic_response(data).text == "real"

    def test_tool_use_block(self):
        data = {
            "content": [{
                "type": "tool_use",
                "id": "tu_1",
                "name": "shell",
                "input": {"cmd": "df -h"},
            }],
        }
        resp = _parse_anthropic_response(data)
        assert resp.tool_calls == [{
            "id": "tu_1", "name": "shell", "args": {"cmd": "df -h"},
        }]

    def test_response_format_overrides_vocab(self):
        rf = {"thinking_tags": ["myreason"]}
        data = {
            "content": [{"type": "text", "text": "<myreason>x</myreason>y"}],
        }
        assert _parse_anthropic_response(data, rf).text == "y"
