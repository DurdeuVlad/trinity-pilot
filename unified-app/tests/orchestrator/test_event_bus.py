"""Tests for event bus behavior."""
from __future__ import annotations

import pytest
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from orchestrator.event_bus import EventBus, get_event_bus


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_singleton_event_bus(app):
    bus1 = get_event_bus()
    bus2 = get_event_bus()
    assert bus1 is bus2


def test_status_signal_emission(app):
    bus = EventBus()
    spy = QSignalSpy(bus.status_update)
    bus.emit_status("hello", "info")
    assert len(spy) == 1
    assert list(spy[0]) == ["hello", "info"]


def test_chat_message_signal_emission(app):
    bus = EventBus()
    spy = QSignalSpy(bus.chat_message)
    bus.chat_message.emit("user", "list files")
    assert len(spy) == 1
    assert list(spy[0]) == ["user", "list files"]


def test_clarification_ready_signal_emission(app):
    bus = EventBus()
    spy = QSignalSpy(bus.clarification_ready)
    bus.clarification_ready.emit("List all Python files.")
    assert len(spy) == 1
    assert list(spy[0]) == ["List all Python files."]


def test_task_result_ready_signal_emission(app):
    bus = EventBus()
    spy = QSignalSpy(bus.task_result_ready)
    bus.task_result_ready.emit("Done! Task completed.")
    assert len(spy) == 1
    assert list(spy[0]) == ["Done! Task completed."]
