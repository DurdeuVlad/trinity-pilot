from __future__ import annotations

from typing import Any

from orchestrator.database import TaskStatus
from orchestrator.event_bus import EventBus


class _Signal:
    def connect(self, _fn: Any) -> None:
        return None


class FakeWatcher:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def start_watching(self) -> None:
        return None

    def stop_watching(self) -> None:
        return None


class RecordingHistoryManager:
    def __init__(self) -> None:
        self.completed_calls: list[dict[str, Any]] = []
        self.step_updates: list[dict[str, Any]] = []

    def create_task(self, *args: Any, **kwargs: Any) -> None:
        return None

    def start_task(self, *args: Any, **kwargs: Any) -> None:
        return None

    def add_step(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_task_plan(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_step_status(
        self,
        task_id: Any,
        step_number: Any,
        status: Any,
        result_data: Any = None,
        error_message: Any = None,
    ) -> None:
        self.step_updates.append(
            {
                "task_id": task_id,
                "step_number": step_number,
                "status": status,
                "result_data": result_data,
                "error_message": error_message,
            }
        )

    def complete_task(
        self,
        task_id: Any,
        result_data: Any = None,
        error_message: Any = None,
        status: Any = None,
    ) -> None:
        derived = (
            status
            if status is not None
            else (TaskStatus.COMPLETED if not error_message else TaskStatus.FAILED)
        )
        self.completed_calls.append(
            {
                "task_id": task_id,
                "result_data": result_data,
                "error_message": error_message,
                "status": derived,
            }
        )

    def close(self) -> None:
        return None


def patch_orchestrator_runtime(monkeypatch: Any, core_module: Any) -> RecordingHistoryManager:
    history = RecordingHistoryManager()
    bus = EventBus()
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    return history
