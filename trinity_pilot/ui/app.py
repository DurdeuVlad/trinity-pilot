from __future__ import annotations

import signal
import sys

import pyautogui
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Kill path 3: PyAutoGUI pointer fail-safe — move mouse to any corner to abort
pyautogui.FAILSAFE = True


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._bridge = None  # WorkflowBridge injected after construction

        self.setWindowTitle("Trinity Pilot")
        self.resize(960, 720)
        self._build_ui()
        self._wire_kill_paths()

    def set_bridge(self, bridge: object) -> None:
        self._bridge = bridge

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(8)

        self._status_label = QLabel("Ready")
        layout.addWidget(self._status_label)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        layout.addWidget(self._log_view)

        row = QHBoxLayout()

        self._input = QLineEdit()
        self._input.setPlaceholderText("Describe your task…")
        self._input.returnPressed.connect(self._handle_submit)
        row.addWidget(self._input)

        # Kill path 1: in-app stop button
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._handle_stop)
        row.addWidget(self._stop_btn)

        layout.addLayout(row)

    def _wire_kill_paths(self) -> None:
        # Kill path 2: global hotkey Ctrl+Shift+Q
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+Q"), self)
        shortcut.activated.connect(self._handle_emergency_stop)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def log(self, message: str) -> None:
        self._log_view.append(message)

    def set_running(self, running: bool) -> None:
        self._stop_btn.setEnabled(running)
        self._input.setEnabled(not running)
        self.set_status("Running…" if running else "Ready")

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _handle_submit(self) -> None:
        task = self._input.text().strip()
        if not task:
            return
        self._input.clear()
        self.log(f"[USER] {task}")
        self.set_running(True)

        if self._bridge:
            self._bridge.start_task(
                user_request=task,
                on_log=self.log,
                on_status=lambda s: self.set_status(f"Status: {s}"),
                on_done=self._on_task_done,
            )

    def _on_task_done(self, final_status: str) -> None:
        self.log(f"[SYSTEM] Task finished: {final_status}")
        self.set_running(False)

    def _handle_stop(self) -> None:
        self.log("[SYSTEM] Stop requested.")
        if self._bridge:
            self._bridge.stop_task()
        self.set_running(False)

    def _handle_emergency_stop(self) -> None:
        self.log("[SYSTEM] Emergency stop (Ctrl+Shift+Q).")
        self._handle_stop()


def run_app() -> None:
    from trinity_pilot.config import Settings
    from trinity_pilot.ui.bridge import WorkflowBridge

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    settings = Settings.from_env()
    bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)

    window = MainWindow()
    window.set_bridge(bridge)
    window.show()
    sys.exit(app.exec())
