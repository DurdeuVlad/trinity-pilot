from __future__ import annotations

import signal
import sys
from typing import Callable

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
    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_submit = on_submit
        self._on_stop = on_stop

        self.setWindowTitle("Trinity Pilot")
        self.resize(960, 720)
        self._build_ui()
        self._wire_kill_paths()

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
    # Public API (used by workflow bridge in Pass 2)
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
        if self._on_submit:
            self._on_submit(task)

    def _handle_stop(self) -> None:
        self.log("[SYSTEM] Stop requested.")
        self.set_running(False)
        if self._on_stop:
            self._on_stop()

    def _handle_emergency_stop(self) -> None:
        self.log("[SYSTEM] Emergency stop (Ctrl+Shift+Q).")
        self._handle_stop()


def run_app() -> None:
    app = QApplication(sys.argv)
    # Allow Ctrl+C in terminal to propagate
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
