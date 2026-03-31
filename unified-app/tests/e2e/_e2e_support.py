"""Shared helpers for real app-session E2E tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

import main as main_module
import orchestrator.event_bus as event_bus_module
from main import MainWindow
from orchestrator.database.models import ExecutionStep, TaskHistory


READY_STARTUP = main_module.StartupReadiness(
    provider_name="gemini",
    ready=True,
    user_message="Startup ready: Gemini live (test).",
    block_task_submission=False,
)


def queue_structured_plan(
    mock: Any,
    *,
    step_description: str,
    domain: str,
    expected_outcome: str,
    estimated_duration: int = 30,
    confidence: float = 0.9,
) -> None:
    """Pre-load a single-step objectives plan into the Gemini mock queue.

    Pushes the ObjectivesDecomposer response so that MacroPlanner returns a
    plan with one step whose description is *step_description*.
    """
    mock.push(json.dumps({"objectives": [step_description]}))


def build_main_window(monkeypatch: Any, tmp_path: Path) -> MainWindow:
    """Create a real app session rooted in a temporary runtime directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    monkeypatch.setattr(
        main_module,
        "_install_stop_hotkey",
        lambda _callback: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(
        main_module,
        "TaskSubmissionPipeServer",
        lambda **_kwargs: SimpleNamespace(start=lambda: None, stop=lambda: None),
    )
    event_bus_module._event_bus_instance = None
    window = MainWindow(startup_readiness=READY_STARTUP)
    window.show()
    return window


def wait_for(predicate: Any, app: QApplication, timeout_seconds: float = 30.0) -> None:
    """Pump Qt events until the predicate becomes true."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for the app session to reach the expected state")


def submit_task_and_collect(
    *,
    app: QApplication,
    window: MainWindow,
    description: str,
    domain_label: str,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Submit a task through the real UI path and return persisted task evidence."""
    done_spy = QSignalSpy(window.event_bus.execution_complete)
    combo = window.task_input_panel.domain_combo
    index = combo.findText(domain_label)
    if index < 0:
        raise AssertionError(f"Unknown domain label: {domain_label}")
    combo.setCurrentIndex(index)
    window.task_input_panel.task_input.setText(description)
    window.task_input_panel.on_run_clicked()

    wait_for(
        lambda: len(done_spy) > 0 and window.task_input_panel.run_btn.isEnabled(),
        app,
        timeout_seconds,
    )
    wait_for(
        lambda: window.orchestrator.current_thread is None and window.orchestrator.current_worker is None,
        app,
        timeout_seconds,
    )

    window.history_view.load_history()
    task_id_item = window.history_view.table.item(0, 4)
    if task_id_item is None:
        raise AssertionError("No history row was written for the submitted task")
    task_id = task_id_item.text()

    history_manager = window.history_view.history_manager
    with history_manager.get_session() as session:
        task = session.query(TaskHistory).filter_by(task_id=task_id).first()
        steps = (
            session.query(ExecutionStep)
            .filter_by(task_id=task_id)
            .order_by(ExecutionStep.step_number.asc())
            .all()
        )

    if task is None:
        raise AssertionError(f"Task {task_id} was not persisted")
    step_payloads = [json.loads(step.result_data or "{}") for step in steps if step.result_data]

    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "error_message": task.error_message,
        "result_data": json.loads(task.result_data or "{}"),
        "step_payloads": step_payloads,
    }
