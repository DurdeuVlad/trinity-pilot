from __future__ import annotations

import signal
import sys
import time
from typing import Any

import pyautogui
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QObject, Signal

from trinity_pilot.ui.chat_widget import ChatState, ChatWidget
from trinity_pilot.ui.stream_worker import StreamWorker

# Kill path 3: PyAutoGUI pointer fail-safe — move mouse to any corner to abort
pyautogui.FAILSAFE = True

_CONFIRM_YES = {"yes", "y", "да", "yep", "sure", "ok", "okay", "run", "go"}
_CONFIRM_NO = {"no", "n", "нет", "cancel", "stop", "abort", "nope"}


class _PlanningRelay(QObject):
    """Marshals planner callbacks from background thread to Qt main thread."""
    planned = Signal(list)   # list[dict]
    error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, debug_mode: bool = False) -> None:
        super().__init__()
        self._bridge: Any = None
        self._debug_mode = debug_mode
        self._settings: Any = None
        self._stream_worker: StreamWorker | None = None
        self._pending_specs: list[dict] = []
        self._pending_request: str = ""
        self._planning_relay = _PlanningRelay(self)
        self._planning_relay.planned.connect(self._on_planning_done)
        self._planning_relay.error.connect(self._on_planning_error)

        self.setWindowTitle("Trinity Pilot")
        self.resize(960, 720)
        self._build_ui()
        self._wire_kill_paths()

    def set_bridge(self, bridge: object) -> None:
        self._bridge = bridge
        self._chat.set_bridge(bridge)

    def set_settings(self, settings: Any) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setStyleSheet("background:#FFFFFF;border-bottom:1px solid #E0E0E0;")
        header.setFixedHeight(44)
        hrow = QHBoxLayout(header)
        hrow.setContentsMargins(12, 0, 12, 0)
        title = QLabel("Trinity Pilot")
        title.setStyleSheet("color:#FF6347;font-weight:700;font-size:15px;")
        hrow.addWidget(title)
        hrow.addStretch()
        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("color:#9E9E9E;font-size:12px;")
        hrow.addWidget(self._status_label)
        if self._debug_mode:
            dbg = QLabel("DEBUG MODE")
            dbg.setStyleSheet(
                "color:#FF6347;font-size:10px;font-weight:700;"
                "background:#FFF3E0;padding:2px 8px;border-radius:8px;"
            )
            hrow.addWidget(dbg)
        layout.addWidget(header)

        # Chat widget (takes remaining space)
        self._chat = ChatWidget(debug_mode=self._debug_mode, parent=root)
        layout.addWidget(self._chat, stretch=1)

        # Input row
        input_bar = QWidget()
        input_bar.setStyleSheet(
            "background:#FFFFFF;border-top:1px solid #E0E0E0;"
        )
        input_bar.setFixedHeight(52)
        row = QHBoxLayout(input_bar)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Describe your task…")
        self._input.returnPressed.connect(self._handle_submit)
        self._input.setStyleSheet(
            "QLineEdit{border:1px solid #E0E0E0;border-radius:18px;"
            "padding:6px 14px;font-size:13px;background:#F9F9F9;}"
            "QLineEdit:focus{border-color:#FF6347;background:white;}"
        )
        row.addWidget(self._input)

        # Kill path 1: in-app stop button
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._handle_stop)
        self._stop_btn.setStyleSheet(
            "QPushButton{background:#FFEBEE;color:#C62828;"
            "border:1px solid #FFCDD2;border-radius:16px;"
            "padding:6px 16px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#FFCDD2;}"
            "QPushButton:disabled{color:#BDBDBD;background:#F5F5F5;border-color:#E0E0E0;}"
        )
        row.addWidget(self._stop_btn)
        layout.addWidget(input_bar)

    def _wire_kill_paths(self) -> None:
        # Kill path 2: global hotkey Ctrl+Shift+Q
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+Q"), self)
        shortcut.activated.connect(self._handle_emergency_stop)

    # ------------------------------------------------------------------
    # Public API (used by run_app and tests)
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def log(self, message: str) -> None:
        if self._debug_mode:
            self._chat.add_system_note(message)

    def set_running(self, running: bool) -> None:
        self._stop_btn.setEnabled(running)
        state = self._chat.get_state()
        if not running and state not in (ChatState.IDLE, ChatState.DONE, ChatState.ERROR):
            self._chat.set_state(ChatState.IDLE)
            self._input.setEnabled(True)
            self._input.setPlaceholderText("Describe your task…")
        self.set_status("Running…" if running else "Ready")

    def update_objective_progress(
        self, objective_id: str, attempt: int, domain: str
    ) -> None:
        self._chat.chips.mark_running(objective_id)

    # ------------------------------------------------------------------
    # Submit routing
    # ------------------------------------------------------------------

    def _handle_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()

        state = self._chat.get_state()
        if state == ChatState.AWAITING_CONFIRM:
            self._handle_confirmation(text)
        elif state in (ChatState.IDLE, ChatState.DONE, ChatState.ERROR):
            self._handle_new_task(text)

    def _handle_new_task(self, task: str) -> None:
        self._pending_request = task
        self._chat.add_user_message(task)
        self._chat.set_state(ChatState.PLANNING)
        self._input.setEnabled(False)
        self._input.setPlaceholderText("Planning…")
        self.set_status("Planning…")
        self._stop_btn.setEnabled(True)

        # Start thinking stream for the AI thoughts bubble
        self._start_thinking_stream(task)

        if not self._bridge:
            self._chat.add_ai_message(
                "No AI bridge connected. Please check your configuration.",
                thought_prompt="Bridge unavailable.",
            )
            self._chat.set_state(ChatState.ERROR)
            self._input.setEnabled(True)
            self._input.setPlaceholderText("Describe your task…")
            self._stop_btn.setEnabled(False)
            return

        self._chat.thinking.start()

        relay = self._planning_relay
        self._bridge.plan_only(
            user_request=task,
            on_planned=lambda specs: relay.planned.emit(specs),
            on_error=lambda err: relay.error.emit(err),
        )

    def _handle_confirmation(self, text: str) -> None:
        lower = text.lower().strip()
        if lower in _CONFIRM_YES:
            self._chat.add_user_message(text)
            self._execute_confirmed()
        elif lower in _CONFIRM_NO:
            self._chat.add_user_message(text)
            self._chat.add_ai_message(
                "Got it, cancelling. Let me know when you want to try again.",
                thought_prompt="User cancelled.",
            )
            self._chat.set_state(ChatState.IDLE)
            self._input.setEnabled(True)
            self._input.setPlaceholderText("Describe your task…")
            self._stop_btn.setEnabled(False)
            self.set_status("Ready")
        else:
            # Treat as amended request — re-plan
            amended = f"{self._pending_request}. {text}"
            self._chat.add_user_message(text)
            self._chat.add_ai_message(
                f"Sure, I'll adjust the plan: \"{text}\". Re-planning now…",
                thought_prompt="User requested amendments.",
            )
            self._handle_new_task(amended)

    def _execute_confirmed(self) -> None:
        self._chat.add_ai_message(
            "Starting execution now. I'll keep you updated as each objective completes.",
            thought_prompt="User confirmed plan. Starting Temporal workflow execution.",
        )
        task_id = self._bridge.start_task(
            user_request=self._pending_request,
            on_log=self.log,
            on_status=lambda s: self.set_status(f"Status: {s}"),
            on_done=self._on_task_done,
        ) if self._bridge else None

        if task_id:
            self._chat.start_task(
                task_id=task_id,
                specs=self._pending_specs,
                start_time=time.monotonic(),
            )
        self._input.setEnabled(False)
        self._input.setPlaceholderText("Executing…")
        self.set_status("Executing…")

    # ------------------------------------------------------------------
    # Task lifecycle callbacks
    # ------------------------------------------------------------------

    def _on_planning_done(self, specs: list) -> None:
        self._chat.thinking.stop()
        self._pending_specs = list(specs)
        self._chat.show_objectives_card(self._pending_specs)
        self._chat.set_state(ChatState.AWAITING_CONFIRM)
        self._input.setEnabled(True)
        self._input.setPlaceholderText("yes / no / describe changes…")
        self.set_status("Awaiting confirmation")

    def _on_planning_error(self, error: str) -> None:
        self._chat.thinking.stop()
        self._chat.add_ai_message(
            f"Sorry, I couldn't plan your task: {error}",
            thought_prompt=f"Planning error: {error}",
        )
        self._chat.set_state(ChatState.ERROR)
        self._input.setEnabled(True)
        self._input.setPlaceholderText("Describe your task…")
        self._stop_btn.setEnabled(False)
        self.set_status("Planning failed")

    def _on_task_done(self, final_status: str) -> None:
        self._chat.thinking.stop()
        self._chat.show_completion(
            status=final_status,
            results={s.get("objective_id", f"obj_{i}"): {"status": "passed" if final_status == "completed" else "failed"}
                     for i, s in enumerate(self._pending_specs)},
        )
        terminal = ChatState.DONE if final_status == "completed" else ChatState.ERROR
        self._chat.set_state(terminal)
        self._input.setEnabled(True)
        self._input.setPlaceholderText("Describe your next task…")
        self._stop_btn.setEnabled(False)
        self.set_status("Done" if final_status == "completed" else f"Finished: {final_status}")

    # ------------------------------------------------------------------
    # Streaming thoughts
    # ------------------------------------------------------------------

    def _start_thinking_stream(self, task: str) -> None:
        if not self._settings:
            return
        prompt = (
            f"The user asked: \"{task}\"\n"
            "In 2-3 short sentences, briefly describe what you are about to plan "
            "(the objectives you will break this into). Be concise."
        )
        self._stream_worker = StreamWorker(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_planner_model,
            prompt=prompt,
            parent=self,
        )
        self._stream_worker.chunk_received.connect(self._chat.on_stream_chunk)
        self._stream_worker.stream_done.connect(self._on_thinking_stream_done)
        self._stream_worker.stream_error.connect(self._on_thinking_stream_error)

        self._chat.add_ai_message(
            "Let me think about this…",
            thought_prompt="",
        )
        self._stream_worker.start()

    def _on_thinking_stream_done(self, full_text: str) -> None:
        pass  # Chunks already delivered live

    def _on_thinking_stream_error(self, error: str) -> None:
        if self._debug_mode:
            self._chat.on_stream_error(error)

    # ------------------------------------------------------------------
    # Kill paths
    # ------------------------------------------------------------------

    def _handle_stop(self) -> None:
        self.log("[SYSTEM] Stop requested.")
        if self._bridge:
            self._bridge.stop_task()
        self._chat.thinking.stop()
        self.set_running(False)

    def _handle_emergency_stop(self) -> None:
        self.log("[SYSTEM] Emergency stop (Ctrl+Shift+Q).")
        self._handle_stop()


def _temporal_reachable(host: str) -> bool:
    """Return True if Temporal gRPC port is open."""
    import socket
    try:
        addr, port_str = host.rsplit(":", 1)
        with socket.create_connection((addr, int(port_str)), timeout=1):
            return True
    except OSError:
        return False


def _start_temporal_if_needed(host: str) -> None:
    """Spawn `temporal server start-dev` in a detached process if not reachable."""
    import shutil
    import subprocess

    if _temporal_reachable(host):
        return
    exe = shutil.which("temporal")
    if not exe:
        return
    subprocess.Popen(
        [exe, "server", "start-dev"],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )
    # Give it a moment to bind
    import time
    for _ in range(20):
        time.sleep(0.5)
        if _temporal_reachable(host):
            break


def run_app() -> None:
    import asyncio
    import threading

    from trinity_pilot.config import Settings
    from trinity_pilot.ui.bridge import WorkflowBridge
    from trinity_pilot.worker_runner import run_worker_async

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    settings = Settings.from_env()

    _start_temporal_if_needed(settings.temporal_host)

    bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)

    window = MainWindow(debug_mode=settings.debug_mode)
    window.set_bridge(bridge)
    window.set_settings(settings)
    window.log("[SYSTEM] Starting worker…")

    def _worker_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_worker_async(
                    settings.temporal_host,
                    on_ready=lambda msg: window.log(f"[WORKER] {msg}"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            window.log(f"[WORKER] Failed to start: {exc}")
        finally:
            loop.close()

    t = threading.Thread(target=_worker_thread, daemon=True, name="trinity-worker")
    t.start()

    window.show()
    sys.exit(app.exec())
