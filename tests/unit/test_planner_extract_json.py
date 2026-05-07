"""Tests for _extract_json — covers common LLM output formats."""
import json

import pytest

from trinity_pilot.planner.planner import _extract_json


class TestExtractJson:
    def test_clean_json_array(self):
        text = '[{"a": 1}]'
        result = _extract_json(text)
        assert json.loads(result) == [{"a": 1}]

    def test_json_fenced_with_language(self):
        text = '```json\n[{"a": 1}]\n```'
        result = _extract_json(text)
        assert json.loads(result) == [{"a": 1}]

    def test_plain_fence(self):
        text = "```\n[{\"b\": 2}]\n```"
        result = _extract_json(text)
        assert json.loads(result) == [{"b": 2}]

    def test_trailing_comma_in_array(self):
        text = '[{"a": 1},]'
        result = _extract_json(text)
        assert json.loads(result) == [{"a": 1}]

    def test_trailing_comma_in_object(self):
        text = '[{"a": 1, "b": 2,}]'
        result = _extract_json(text)
        assert json.loads(result) == [{"a": 1, "b": 2}]

    def test_extra_whitespace_and_newlines(self):
        text = '\n\n  [{"x": 99}]  \n'
        result = _extract_json(text)
        assert json.loads(result) == [{"x": 99}]

    def test_partial_fence_no_closing(self):
        """LLM truncates response mid-output — no closing ```."""
        text = "```json\n[{\"c\": 3}]"
        result = _extract_json(text)
        assert json.loads(result) == [{"c": 3}]
