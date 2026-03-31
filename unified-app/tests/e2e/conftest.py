from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

import main as main_module
import orchestrator.event_bus as event_bus_module
import orchestrator.orchestrator_core as core_module
import ui.views.history_view as history_view_module
from orchestrator.database.manager import HistoryManager
from orchestrator.database.models import ExecutionStep


@dataclass
class CompletedSession:
    """Captured state from one real app-session submission."""

    payload: dict[str, Any]
    history_status: str
    log_text: str
    status_updates: list[tuple[str, str]]
    task: Any
    step_payloads: list[dict[str, Any]]


class AppSessionHarness:
    """Drive the Unified App through the UI submission entrypoint."""

    def __init__(self, window: main_module.MainWindow, qtbot: Any, db_path: Path, bus: Any) -> None:
        self.window = window
        self.qtbot = qtbot
        self.db_path = db_path
        self.bus = bus

    def _read_latest_task(self) -> tuple[Any, list[dict[str, Any]]]:
        history_manager = HistoryManager(str(self.db_path))
        try:
            tasks = history_manager.get_recent_tasks(limit=1)
            assert tasks, "No task history rows were written"
            task = tasks[0]
            with history_manager.get_session() as session:
                steps = (
                    session.query(ExecutionStep)
                    .filter_by(task_id=task.task_id)
                    .order_by(ExecutionStep.step_number)
                    .all()
                )
                step_payloads = [json.loads(step.result_data or "{}") for step in steps]
            return task, step_payloads
        finally:
            history_manager.close()

    def run_task(self, description: str, domain_label: str, timeout_ms: int = 30000) -> CompletedSession:
        """Submit one task through the UI and return the observable outputs."""

        execution_spy = QSignalSpy(self.bus.execution_complete)
        status_spy = QSignalSpy(self.bus.status_update)

        self.window.status_log_panel.clear_log()
        self.window.task_input_panel.task_input.setPlainText(description)
        self.window.task_input_panel.domain_combo.setCurrentText(domain_label)
        self.window.task_input_panel.on_run_clicked()

        self.qtbot.waitUntil(lambda: len(execution_spy) > 0, timeout=timeout_ms)
        self.qtbot.waitUntil(
            lambda: self.window.task_input_panel.run_btn.isEnabled(),
            timeout=timeout_ms,
        )

        self.window.history_view.load_history()
        task, step_payloads = self._read_latest_task()
        history_status_item = self.window.history_view.table.item(0, 3)
        assert history_status_item is not None, "History table did not render a status cell"

        payload = execution_spy[-1][0]
        status_updates = [(str(args[0]), str(args[1])) for args in status_spy]

        return CompletedSession(
            payload=payload,
            history_status=history_status_item.text(),
            log_text=self.window.status_log_panel.log_text.toPlainText(),
            status_updates=status_updates,
            task=task,
            step_payloads=step_payloads,
        )


@pytest.fixture(scope="session")
def app() -> QApplication:
    """Provide a single QApplication for E2E-style UI tests."""

    return QApplication.instance() or QApplication([])


@pytest.fixture
def app_session_harness(app: QApplication, qtbot: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Create an isolated MainWindow session backed by a temporary history DB."""

    _ = app
    db_path = tmp_path / "orchestrator_history.db"

    def make_history_manager() -> HistoryManager:
        return HistoryManager(str(db_path))

    monkeypatch.setenv("GEMINI_MOCK", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    event_bus_module._event_bus_instance = None
    monkeypatch.setattr(core_module, "HistoryManager", make_history_manager)
    monkeypatch.setattr(history_view_module, "HistoryManager", make_history_manager)

    startup_readiness = main_module.StartupReadiness(
        mode="mock",
        ready=True,
        user_message="Startup mode: mock fallback ready.",
        block_task_submission=False,
    )
    window = main_module.MainWindow(startup_readiness=startup_readiness)
    qtbot.addWidget(window)
    window.show()

    yield AppSessionHarness(
        window=window,
        qtbot=qtbot,
        db_path=db_path,
        bus=event_bus_module.get_event_bus(),
    )

    window.close()
    app.processEvents()  # flush all pending deleteLater() events before clearing singleton
    event_bus_module._event_bus_instance = None
