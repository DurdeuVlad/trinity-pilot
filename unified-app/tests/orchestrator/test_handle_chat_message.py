"""Tests for OrchestratorCore.handle_chat_message and related chat lifecycle.

Cross-thread Qt signals are tested by:
1. Connecting regular Python callbacks to the bus signals.
2. Joining the background thread so it has finished emitting.
3. Calling app.processEvents() to deliver any queued cross-thread signal calls.
"""
from __future__ import annotations

import time

import pytest
from PyQt6.QtWidgets import QApplication

import orchestrator.orchestrator_core as core_module
from orchestrator.event_bus import EventBus
from orchestrator.orchestrator_core import OrchestratorCore


# ---------------------------------------------------------------------------
# QApplication fixture — needed to dispatch queued (cross-thread) signals
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Provider stubs
# ---------------------------------------------------------------------------


class ReadyProvider:
    """Provider that immediately returns READY."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return "READY: List all Python files."

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class QuestionProvider:
    """Provider that asks a clarifying question."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return "Which directory would you like to list?"

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class ErrorProvider:
    """Provider that always raises."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        raise RuntimeError("provider unavailable")

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_core(monkeypatch, provider, bus: EventBus) -> OrchestratorCore:
    """Build an OrchestratorCore with stubbed dependencies."""

    class FakeSettingsManager:
        def load(self) -> dict:
            return {
                "ai_provider": "gemini",
                "gemini_api_key": "test-key",
                "openai_api_key": "",
            }

    monkeypatch.setattr(core_module, "SettingsManager", lambda: FakeSettingsManager())
    monkeypatch.setattr(core_module, "make_provider", lambda _name, _key: provider)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    return OrchestratorCore()


def _drain(app: QApplication, core: OrchestratorCore, timeout: float = 3.0) -> None:
    """Join the background thread, then flush queued Qt signals."""
    thread = core._clarification_thread
    if thread is not None:
        thread.join(timeout=timeout)
    app.processEvents()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_chat_message_ready_emits_assistant_message(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, ReadyProvider(), bus)

    emitted: list[tuple[str, str]] = []
    bus.chat_message.connect(lambda role, text: emitted.append((role, text)))

    core.handle_chat_message("list python files")
    _drain(app, core)

    assert any(role == "assistant" for role, _ in emitted)


def test_handle_chat_message_ready_emits_clarification_ready(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, ReadyProvider(), bus)

    ready_emitted: list[str] = []
    bus.chat_message.connect(lambda role, text: None)
    bus.clarification_ready.connect(lambda task: ready_emitted.append(task))

    core.handle_chat_message("list python files")
    _drain(app, core)

    assert ready_emitted == ["List all Python files."]


def test_handle_chat_message_question_does_not_emit_clarification_ready(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, QuestionProvider(), bus)

    ready_emitted: list[str] = []
    bus.chat_message.connect(lambda role, text: None)
    bus.clarification_ready.connect(lambda task: ready_emitted.append(task))

    core.handle_chat_message("list files")
    _drain(app, core)

    assert ready_emitted == []


def test_handle_chat_message_question_emits_assistant_text(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, QuestionProvider(), bus)

    emitted: list[tuple[str, str]] = []
    bus.chat_message.connect(lambda role, text: emitted.append((role, text)))

    core.handle_chat_message("list files")
    _drain(app, core)

    assistant_msgs = [text for role, text in emitted if role == "assistant"]
    assert assistant_msgs
    assert any("?" in msg for msg in assistant_msgs)


def test_handle_chat_message_provider_error_still_emits_assistant_message(app, monkeypatch) -> None:
    """When the LLM provider fails, ClarificationEngine falls back to ready=True.

    The orchestrator core should still emit a chat_message to the assistant channel
    so the user sees a response rather than silence.
    """
    bus = EventBus()
    core = _make_core(monkeypatch, ErrorProvider(), bus)

    emitted: list[tuple[str, str]] = []
    bus.chat_message.connect(lambda role, text: emitted.append((role, text)))
    # Capture clarification_ready to avoid "no slots" warning
    bus.clarification_ready.connect(lambda task: None)

    core.handle_chat_message("do something")
    _drain(app, core)

    # ClarificationEngine treats provider failure as ready=True, so orchestrator
    # core emits the "Got it — I'm ready to run" assistant message.
    assistant_msgs = [text for role, text in emitted if role == "assistant"]
    assert assistant_msgs, "Expected at least one assistant chat_message on provider error"


def test_handle_chat_message_startup_guard_responds_immediately(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, ReadyProvider(), bus)
    core.set_startup_guard("Live Gemini blocked: invalid API key.")

    emitted: list[tuple[str, str]] = []
    bus.chat_message.connect(lambda role, text: emitted.append((role, text)))

    core.handle_chat_message("list files")
    # Startup guard is a synchronous code path — no background thread
    time.sleep(0.05)
    app.processEvents()

    assert ("assistant", "Live Gemini blocked: invalid API key.") in emitted
    assert core._clarification_thread is None or not core._clarification_thread.is_alive()


def test_reset_chat_session_clears_engine_history(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, QuestionProvider(), bus)

    # Trigger a turn to populate history (suppress signal delivery noise)
    bus.chat_message.connect(lambda role, text: None)
    core.handle_chat_message("open chrome")
    _drain(app, core)

    assert core._clarification_engine is not None
    assert len(core._clarification_engine._history) > 0

    core.reset_chat_session()

    assert core._clarification_engine._history == []


def test_clarification_engine_is_reused_across_turns(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, QuestionProvider(), bus)

    bus.chat_message.connect(lambda role, text: None)

    core.handle_chat_message("turn 1")
    _drain(app, core)
    engine_first = core._clarification_engine

    core.handle_chat_message("turn 2")
    _drain(app, core)
    engine_second = core._clarification_engine

    assert engine_first is engine_second


def test_ready_message_text_contains_confirmed_task(app, monkeypatch) -> None:
    bus = EventBus()
    core = _make_core(monkeypatch, ReadyProvider(), bus)

    emitted: list[tuple[str, str]] = []
    bus.chat_message.connect(lambda role, text: emitted.append((role, text)))
    bus.clarification_ready.connect(lambda task: None)

    core.handle_chat_message("list python files")
    _drain(app, core)

    assistant_msgs = [text for role, text in emitted if role == "assistant"]
    assert any("List all Python files" in msg for msg in assistant_msgs)
