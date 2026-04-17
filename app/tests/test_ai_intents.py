"""Tests for ai_intents.py — parse_text_only and AnalysisResponse."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ai_intents import parse_text_only, AnalysisResponse


class TestParseTextOnly:
    def test_plain_text_no_tags(self):
        resp = parse_text_only("Hello, this is a normal response.")
        assert resp.text == "Hello, this is a normal response."
        assert resp.memory_ops == []
        assert resp.raw_text == "Hello, this is a normal response."

    def test_extracts_memory_tags(self):
        raw = "The device is a PiKVM V3. [MEMORY: device_info | PiKVM V3 hardware] Done."
        resp = parse_text_only(raw)
        assert len(resp.memory_ops) == 1
        assert resp.memory_ops[0]["category"] == "device_info"
        assert resp.memory_ops[0]["content"] == "PiKVM V3 hardware"
        assert "[MEMORY:" not in resp.text
        assert "Done." in resp.text

    def test_extracts_multiple_memory_tags(self):
        raw = "[MEMORY: user_pref | dark mode] User prefers dark mode. [MEMORY: knowledge | SSH port 22]"
        resp = parse_text_only(raw)
        assert len(resp.memory_ops) == 2
        assert resp.memory_ops[0]["category"] == "user_pref"
        assert resp.memory_ops[1]["category"] == "knowledge"

    def test_strips_code_fences(self):
        raw = "Here is code:\n```json\n{\"key\": \"value\"}\n```\nDone."
        resp = parse_text_only(raw)
        assert "```" not in resp.text
        assert "Done." in resp.text

    def test_collapses_excessive_newlines(self):
        raw = "Line 1\n\n\n\n\nLine 2"
        resp = parse_text_only(raw)
        assert "\n\n\n" not in resp.text

    def test_preserves_raw_text(self):
        raw = "[MEMORY: test | data] Some text ```code```"
        resp = parse_text_only(raw)
        assert resp.raw_text == raw
        assert "[MEMORY:" in resp.raw_text  # raw preserved

    def test_empty_input(self):
        resp = parse_text_only("")
        assert resp.text == ""
        assert resp.memory_ops == []


class TestAnalysisResponse:
    def test_dataclass_creation(self):
        resp = AnalysisResponse(raw_text="raw", text="clean", memory_ops=[{"category": "a", "content": "b"}])
        assert resp.raw_text == "raw"
        assert resp.text == "clean"
        assert len(resp.memory_ops) == 1

    def test_default_memory_ops(self):
        resp = AnalysisResponse(raw_text="r", text="t")
        assert resp.memory_ops == []
