"""MainWindow — wires ChatPanel, PlanPanel, StatusPanel to OrchestratorCore."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QSplitter

from event_bus import get_event_bus
from orchestrator import OrchestratorCore
from settings import get_settings
from ui.chat_panel import ChatPanel
from ui.plan_panel import PlanPanel
from ui.status_panel import StatusPanel
from ui.theme import app_stylesheet


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._current_task = ""
        self._orchestrator = OrchestratorCore()
        self._setup_ui()
        self._connect_signals()
        self._check_api_key()

    def _setup_ui(self) -> None:
        self.setWindowTitle("TrinityPilot")
        self.setMinimumSize(900, 600)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setChildrenCollapsible(False)

        self._chat = ChatPanel()
        self._plan = PlanPanel()
        self._status = StatusPanel()

        splitter.addWidget(self._chat)
        splitter.addWidget(self._plan)
        splitter.addWidget(self._status)

        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)

        self.setCentralWidget(splitter)

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_stylesheet())

    def _connect_signals(self) -> None:
        bus = get_event_bus()

        # UI → orchestrator
        self._chat.task_submitted.connect(self._on_task_submitted)
        self._plan.run_clicked.connect(self._on_run_clicked)
        self._plan.cancel_clicked.connect(self._orchestrator.cancel)

        # Event bus → panels
        bus.plan_ready.connect(self._on_plan_ready)
        bus.plan_failed.connect(self._on_plan_failed)
        bus.chat_reply.connect(lambda text: self._chat.show_message(text))
        bus.execution_started.connect(self._status.clear)
        bus.step_started.connect(self._plan.set_step_active)
        bus.step_done.connect(self._plan.set_step_done)
        bus.execution_done.connect(self._on_execution_done)
        bus.status_message.connect(self._status.append)
        bus.busy_changed.connect(self._on_busy_changed)
        bus.task_cancelled.connect(self._on_cancelled)

    def _check_api_key(self) -> None:
        settings = get_settings()
        provider = str(settings.get("ai_provider", "gemini")).lower()
        if provider == "openai":
            key = os.getenv("OPENAI_API_KEY") or str(settings.get("openai_api_key", ""))
            var = "OPENAI_API_KEY"
        else:
            key = os.getenv("GEMINI_API_KEY") or str(settings.get("gemini_api_key", ""))
            var = "GEMINI_API_KEY"

        if not key.strip():
            self._chat.show_message(
                f"No API key found. Set {var} in your environment or settings.json.",
                role="assistant",
            )
        else:
            self._chat.show_message(
                f"Ready ({provider}). Describe your automation task below.",
                role="assistant",
            )

    def _on_task_submitted(self, task: str) -> None:
        self._current_task = task
        self._orchestrator.start_planning(task)

    def _on_plan_ready(self, objectives: list[str]) -> None:
        self._plan.show_plan(objectives)
        self._chat.show_message(
            f"Plan ready ({len(objectives)} sub-objective{'s' if len(objectives) != 1 else ''}). "
            "Review the plan and click Run, or edit sub-objectives first.",
            role="assistant",
        )
        from orchestrator.trinity_bridge import TrinityBridge
        domain = TrinityBridge().suggest_domain(self._current_task)
        self._plan.set_domain(domain)

    def _on_plan_failed(self, error: str) -> None:
        self._chat.show_message(
            f"Could not generate a plan: {error}. Try rephrasing your task.",
            role="assistant",
        )

    def _on_run_clicked(self, objectives: list[str]) -> None:
        self._plan.set_executing(True)
        self._orchestrator.start_execution(self._current_task, objectives)

    def _on_execution_done(self, success: bool, output: str) -> None:
        self._plan.set_executing(False)
        self._chat.show_result(success, output)

    def _on_busy_changed(self, busy: bool) -> None:
        self._chat.set_busy(busy)

    def _on_cancelled(self) -> None:
        self._plan.set_executing(False)
        self._chat.show_message("Execution cancelled.", role="assistant")
        self._chat.set_busy(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._orchestrator.shutdown():
            event.ignore()
            return
        super().closeEvent(event)
