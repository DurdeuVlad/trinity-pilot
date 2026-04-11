"""Qt event bus for decoupled orchestrator communication."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class EventBus(QObject):
    """Central event hub used by UI panels and orchestrator core."""

    task_submitted = pyqtSignal(str, str)
    pipe_task_submitted = pyqtSignal(str, str, str)
    pipe_task_registered = pyqtSignal(str, str)
    steer_input = pyqtSignal(str)
    task_cancel_requested = pyqtSignal()
    task_policy_stop_requested = pyqtSignal(str)
    plan_generated = pyqtSignal(list)
    step_started = pyqtSignal(int, str)
    step_completed = pyqtSignal(int, dict)
    step_failed = pyqtSignal(int, object)
    # (obj_idx, step_num, action_type, result_summary) — one per action turn
    step_detail = pyqtSignal(int, int, str, str)
    plan_state_updated = pyqtSignal(int, dict)
    status_update = pyqtSignal(str, str)
    cli_step_progress = pyqtSignal(int, dict)  # (obj_index, step_payload)
    execution_complete = pyqtSignal(dict)
    app_busy = pyqtSignal(bool)
    execution_started = pyqtSignal()
    execution_ended = pyqtSignal()
    run_started = pyqtSignal(str)
    run_ended = pyqtSignal(str)
    desktop_takeover_started = pyqtSignal(str)  # payload: "browser" | "desktop" | "mixed"
    desktop_takeover_ended = pyqtSignal()
    preflight_done = pyqtSignal(object)  # payload: StartupReadiness

    # ── Chat / clarification signals ────────────────────────────────────
    chat_message = pyqtSignal(str, str)   # (role: "user"|"assistant", text)
    clarification_ready = pyqtSignal(str) # confirmed task summary
    objectives_preview_ready = pyqtSignal(str, list)  # confirmed task summary, proposed objectives
    objectives_modify_done = pyqtSignal(bool)  # True = success (preview_ready also fires), False = rejected
    task_result_ready = pyqtSignal(str, dict)  # (final_answer, summary_dict)

    # ── Human-in-the-loop pause signals ─────────────────────────────────
    blocker_detected = pyqtSignal(str)   # message: what the user needs to do
    blocker_resolved = pyqtSignal()      # user confirmed they're done

    def emit_status(self, message: str, level: str = "info") -> None:
        """Emit status line with level metadata."""
        self._mirror_status_to_console(message, level)
        self.status_update.emit(message, level)

    @staticmethod
    def _mirror_status_to_console(message: str, level: str) -> None:
        try:
            stream = getattr(sys, "stdout", None)
            if stream is None or getattr(stream, "closed", False):
                return
            print(f"[{level}] {message}", file=stream, flush=True)
        except Exception:
            return

    def set_busy(self, busy: bool) -> None:
        """Broadcast application busy state."""
        self.app_busy.emit(busy)

    @pyqtSlot(str, str)
    def submit_task_from_pipe(self, description: str, domain: str) -> None:
        """Bridge pipe submissions onto the app thread before re-emitting them."""
        self.task_submitted.emit(description, domain)

    @pyqtSlot(str, str, str)
    def submit_task_request_from_pipe(self, description: str, domain: str, request_id: str) -> None:
        """Bridge request-aware pipe submissions onto the app thread."""
        self.pipe_task_submitted.emit(description, domain, request_id)


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
