"""Tests for ClarificationEngine — intent clarification pre-flight."""
from __future__ import annotations

import pytest

from orchestrator.clarification_engine import ClarificationEngine, ClarificationResult


# ---------------------------------------------------------------------------
# Minimal provider stubs
# ---------------------------------------------------------------------------


class ReadyProvider:
    """Returns a READY response for any message."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return "READY: List all Python files in the current directory."

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class QuestionProvider:
    """Returns a clarifying question for any message."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return "What would you like me to search for, and on which website?"

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class ErrorProvider:
    """Always raises an exception."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        raise RuntimeError("provider unreachable")

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class RecordingProvider:
    """Records messages passed to it; returns a READY response."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        self.calls.append(messages)
        return "READY: Echo hello test."

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ready_response_is_parsed_correctly() -> None:
    engine = ClarificationEngine(ReadyProvider())
    result = await engine.process("list all python files")

    assert isinstance(result, ClarificationResult)
    assert result.ready is True
    assert result.confirmed_task == "List all Python files in the current directory."
    assert result.text.upper().startswith("READY:")


@pytest.mark.asyncio
async def test_non_ready_question_response() -> None:
    engine = ClarificationEngine(QuestionProvider())
    result = await engine.process("search for something")

    assert isinstance(result, ClarificationResult)
    assert result.ready is False
    assert result.confirmed_task is None
    assert "?" in result.text


@pytest.mark.asyncio
async def test_error_fallback_treats_request_as_ready() -> None:
    engine = ClarificationEngine(ErrorProvider())
    result = await engine.process("list files")

    assert result.ready is True
    assert result.confirmed_task == "list files"


@pytest.mark.asyncio
async def test_error_fallback_text_contains_exception_message() -> None:
    engine = ClarificationEngine(ErrorProvider())
    result = await engine.process("do something")

    # text carries the exception string, not a READY line
    assert "unreachable" in result.text


@pytest.mark.asyncio
async def test_conversation_history_is_built_correctly() -> None:
    provider = RecordingProvider()
    engine = ClarificationEngine(provider)
    await engine.process("echo hello test")

    assert len(provider.calls) == 1
    messages = provider.calls[0]
    # First message is always the system prompt
    assert messages[0]["role"] == "system"
    # Second message is the user turn
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "echo hello test"


@pytest.mark.asyncio
async def test_conversation_history_accumulates_across_turns() -> None:
    provider = QuestionProvider()
    engine = ClarificationEngine(provider)

    await engine.process("open chrome")
    await engine.process("just open it normally")

    # After two turns, engine._history has 4 entries (2 user + 2 assistant)
    assert len(engine._history) == 4
    assert engine._history[0]["role"] == "user"
    assert engine._history[1]["role"] == "assistant"
    assert engine._history[2]["role"] == "user"
    assert engine._history[3]["role"] == "assistant"


@pytest.mark.asyncio
async def test_reset_clears_history() -> None:
    provider = QuestionProvider()
    engine = ClarificationEngine(provider)

    await engine.process("open chrome")
    assert len(engine._history) == 2

    engine.reset()

    assert engine._history == []


@pytest.mark.asyncio
async def test_ready_prefix_is_case_insensitive() -> None:
    class LowercaseReadyProvider:
        async def call(self, messages, *, json_mode=True):
            return "ready: Open Google Chrome browser."

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    engine = ClarificationEngine(LowercaseReadyProvider())
    result = await engine.process("open chrome")

    assert result.ready is True
    assert result.confirmed_task == "Open Google Chrome browser."


@pytest.mark.asyncio
async def test_ready_confirmed_task_strips_whitespace() -> None:
    class PaddedProvider:
        async def call(self, messages, *, json_mode=True):
            return "READY:   List files.   "

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    engine = ClarificationEngine(PaddedProvider())
    result = await engine.process("list files")

    assert result.confirmed_task == "List files."
