"""Tests for error handler payloads."""
from __future__ import annotations

import pytest

from orchestrator.error_handler import ErrorHandler


def test_error_handler_payload():
    handler = ErrorHandler()
    payload = handler.handle(ValueError("bad input"), context="Planner")
    assert payload["type"] == "ValueError"
    assert "bad input" in payload["message"]
    assert "Planner" in payload["user_message"]


def test_error_handler_sanitizes_traceback_for_user_message():
    handler = ErrorHandler()
    raw = (
        "Traceback (most recent call last):\n"
        "  File \"runner.py\", line 1, in <module>\n"
        "RuntimeError: gemini call failed with secret details"
    )
    payload = handler.handle(RuntimeError(raw), context="Execution")
    assert "Traceback" in payload["message"]
    assert "Traceback" not in payload["user_message"]
    assert "File \"runner.py\"" not in payload["user_message"]
    assert "Execution:" in payload["user_message"]


def test_error_handler_prefers_contract_category_when_supplied():
    handler = ErrorHandler()
    payload = handler.handle(
        RuntimeError("some low-level timeout exception text"),
        context="Execution",
        category="auth_failure",
    )

    assert payload["category"] == "auth_failure"
    assert "authentication failed" in payload["user_message"].lower()


@pytest.mark.parametrize(
    ("category", "expected_snippet"),
    [
        ("auth_failure", "Authentication failed"),
        ("timeout", "request timed out"),
        ("backend_error", "backend encountered an error"),
        ("user_error", "could not be understood"),
        ("cancelled", "task was cancelled"),
    ],
)
def test_error_handler_uses_contract_message_templates(category: str, expected_snippet: str):
    handler = ErrorHandler()
    message = handler.build_user_message("raw backend text", category=category)
    assert expected_snippet.lower() in message.lower()


@pytest.mark.parametrize(
    ("raw_message", "expected_category", "expected_snippet"),
    [
        ("API_KEY_INVALID: key not valid", "auth_failure", "Authentication failed"),
        ("429 ResourceExhausted: quota hit", "backend_error", "backend encountered an error"),
        ("ConnectionError: network unreachable", "backend_error", "backend encountered an error"),
        ("JSONDecodeError: invalid plan json", "user_error", "could not be understood"),
    ],
)
def test_error_handler_classifies_live_gemini_failures(
    raw_message: str,
    expected_category: str,
    expected_snippet: str,
):
    handler = ErrorHandler()
    payload = handler.handle(RuntimeError(raw_message), context="Execution")

    assert payload["category"] == expected_category
    assert expected_snippet in payload["user_message"]
