"""Qt event bus for decoupled orchestrator communication."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class EventBus(QObject):
    """Central event hub used by UI panels and orchestrator core."""

    task_submitted = pyqtSignal(str, str)
    task_cancel_requested = pyqtSignal()
    plan_generated = pyqtSignal(list)
    step_started = pyqtSignal(int, str)
    step_completed = pyqtSignal(int, dict)
    step_failed = pyqtSignal(int, str)
    status_update = pyqtSignal(str, str)
    execution_complete = pyqtSignal(dict)
    app_busy = pyqtSignal(bool)
    frame_captured = pyqtSignal(str)
    frame_rate_updated = pyqtSignal(float)
    execution_started = pyqtSignal()
    execution_ended = pyqtSignal()
    desktop_takeover_started = pyqtSignal(str)  # payload: "browser" | "desktop" | "mixed"
    desktop_takeover_ended = pyqtSignal()
    preflight_done = pyqtSignal(object)  # payload: StartupReadiness

    # ── Chat / clarification signals ────────────────────────────────────
    chat_message = pyqtSignal(str, str)   # (role: "user"|"assistant", text)
    clarification_ready = pyqtSignal(str) # confirmed task summary
    task_result_ready = pyqtSignal(str)   # final answer to show back in chat

    def emit_status(self, message: str, level: str = "info") -> None:
        """Emit status line with level metadata."""
        self.status_update.emit(message, level)

    def set_busy(self, busy: bool) -> None:
        """Broadcast application busy state."""
        self.app_busy.emit(busy)

    @pyqtSlot(str, str)
    def submit_task_from_pipe(self, description: str, domain: str) -> None:
        """Bridge pipe submissions onto the app thread before re-emitting them."""
        self.task_submitted.emit(description, domain)


_event_bus_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return process-wide EventBus singleton, recreating it if the C++ object was deleted."""
    global _event_bus_instance
    if _event_bus_instance is not None:
        try:
            _event_bus_instance.objectName()  # raises RuntimeError if C++ object is gone
        except RuntimeError:
            _event_bus_instance = None
    if _event_bus_instance is None:
        _event_bus_instance = EventBus()
    return _event_bus_instance
