"""Central event bus — 10 signals, one singleton."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

_bus: "EventBus | None" = None


class EventBus(QObject):
    plan_ready = pyqtSignal(list)        # list[str] objectives
    plan_failed = pyqtSignal(str)        # error message
    execution_started = pyqtSignal()
    step_started = pyqtSignal(int, str)  # (n, objective text)
    step_done = pyqtSignal(int, bool, str)  # (n, success, output)
    execution_done = pyqtSignal(bool, str)  # (success, output)
    status_message = pyqtSignal(str, str)   # (text, level: info/step/success/error)
    task_cancelled = pyqtSignal()
    busy_changed = pyqtSignal(bool)
    chat_reply = pyqtSignal(str)         # assistant message for chat panel


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
