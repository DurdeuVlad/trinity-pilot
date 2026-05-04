"""Unit tests for Session.get_context_window() — window truncation and failure pinning."""

import pytest

from trinity_core.session import Session
from trinity_core.tools.base import ToolResult


def _make_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Session(session_id="test-ctx")


def _add_turn(session: Session, *, success: bool = True) -> None:
    """Append a user message + tool result pair."""
    session.append_user_message("do something")
    session.append_tool_result(
        "call-x",
        "some_tool",
        ToolResult(status="success" if success else "error", output="result"),
    )


def test_window_truncates_keeping_failures(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    # 3 failures + 27 non-failure messages (14 user + 13 success tool = 27)
    for _ in range(3):
        session.append_user_message("task")
        session.append_tool_result("c", "t", ToolResult(status="error", output="err"))
    for _ in range(13):
        _add_turn(session, success=True)

    result = session.get_context_window(max_messages=20)
    assert len(result) == 20
    failure_msgs = [m for m in result if m.get("role") == "tool" and m.get("status") != "success"]
    assert len(failure_msgs) == 3


def test_no_truncation_when_total_under_limit(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    for _ in range(5):
        _add_turn(session, success=True)

    result = session.get_context_window(max_messages=20)
    assert len(result) == 10  # 5 user + 5 tool


def test_all_failures_never_capped(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    for _ in range(25):
        session.append_user_message("task")
        session.append_tool_result("c", "t", ToolResult(status="error", output="err"))

    result = session.get_context_window(max_messages=20)
    # All 25 failure tool results must be present
    failure_msgs = [m for m in result if m.get("role") == "tool" and m.get("status") != "success"]
    assert len(failure_msgs) == 25


def test_empty_session_returns_empty(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    assert session.get_context_window(max_messages=20) == []


def test_early_failure_preserved_beyond_window(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    # Failure at very start
    session.append_user_message("first")
    session.append_tool_result("c0", "t", ToolResult(status="error", output="early fail"))
    # 29 more non-failure messages
    for _ in range(14):
        _add_turn(session, success=True)

    result = session.get_context_window(max_messages=10)
    # The early failure tool result must be present
    early_failure = next(
        (m for m in result if m.get("role") == "tool" and m.get("status") != "success"), None
    )
    assert early_failure is not None
    assert early_failure["content"] == "early fail"


def test_chronological_order_preserved(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    for i in range(5):
        session.append_user_message(f"msg-{i}")
        session.append_tool_result(
            f"c{i}", "t", ToolResult(status="error" if i == 2 else "success", output=f"out-{i}")
        )

    result = session.get_context_window(max_messages=20)
    contents = [m.get("content") or m.get("output", "") for m in result if m.get("role") in ("user", "tool")]
    # Order must be preserved — check user messages are in original order
    user_contents = [m["content"] for m in result if m.get("role") == "user"]
    assert user_contents == sorted(user_contents)  # msg-0..msg-4 lexicographic = chronological


def test_default_max_messages_is_20(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    for _ in range(15):
        _add_turn(session, success=True)

    result_default = session.get_context_window()
    result_explicit = session.get_context_window(max_messages=20)
    assert result_default == result_explicit


def test_non_failure_messages_use_recency(tmp_path, monkeypatch):
    session = _make_session(tmp_path, monkeypatch)
    for i in range(10):
        _add_turn(session, success=True)

    result = session.get_context_window(max_messages=6)
    user_msgs = [m for m in result if m.get("role") == "user"]
    # Should contain only the last 3 user messages (paired with 3 success tool results = 6 total)
    assert len(user_msgs) == 3
    contents = [m["content"] for m in user_msgs]
    assert all(c == "do something" for c in contents)
