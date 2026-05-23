from __future__ import annotations

import json
import signal
import sys
import time
from typing import Any

import pyautogui
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextBrowser,
    QToolButton,
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


class _ClarificationRelay(QObject):
    """Marshals clarification-check results back to the Qt main thread."""
    question = Signal(str)        # clarification needed — emit the question
    clear = Signal()              # automate intent, task clear — proceed to planning
    direct_response = Signal(str, str)  # (intent, task) — chat/consult, skip planning



class _DebugDrawer(QWidget):
    """Read-only state inspector panel. Shows ChatState, pending specs, request, progress."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._browser.setFont(mono)
        self._browser.setStyleSheet(
            "QTextBrowser{background:#212121;color:#80CBC4;"
            "font-family:Consolas,monospace;font-size:10px;"
            "border:none;padding:4px;}"
        )
        layout.addWidget(self._browser)

    def update(  # type: ignore[override]
        self,
        state: ChatState,
        pending_specs: list,
        pending_request: str,
        progress: dict | None,
    ) -> None:
        """Populate the panel with a formatted state dump."""
        lines: list[str] = []
        lines.append(f"ChatState: {state.name}")
        lines.append(f"Pending request: {pending_request!r}")
        lines.append(f"Pending specs ({len(pending_specs)}):")
        for i, spec in enumerate(pending_specs):
            obj_id = spec.get("objective_id", f"obj_{i}")
            domain = spec.get("domain", "?")
            lines.append(f"  [{i}] objective_id={obj_id} domain={domain}")
        if pending_specs:
            lines.append("")
            try:
                lines.append(json.dumps(pending_specs, indent=2))
            except (TypeError, ValueError):
                lines.append(str(pending_specs))
        lines.append(f"Last progress: {progress!r}")
        self._browser.setPlainText("\n".join(lines))


class MainWindow(QMainWindow):
    def __init__(self, debug_mode: bool = False) -> None:
        super().__init__()
        self._bridge: Any = None
        self._debug_mode = debug_mode
        self._dark = False
        self._settings: Any = None
        self._stream_worker: StreamWorker | None = None
        self._pending_specs: list[dict] = []
        self._pending_request: str = ""
        self._planning_relay = _PlanningRelay(self)
        self._planning_relay.planned.connect(self._on_planning_done)
        self._planning_relay.error.connect(self._on_planning_error)

        self._clarification_relay = _ClarificationRelay(self)
        self._clarification_relay.question.connect(self._on_clarification_needed)
        self._clarification_relay.clear.connect(self._on_clarification_clear)
        self._clarification_relay.direct_response.connect(self._on_direct_response)


        # Debug drawer — only instantiated when debug_mode=True
        if self._debug_mode:
            self._debug_drawer: _DebugDrawer | None = _DebugDrawer()
        else:
            self._debug_drawer = None

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
        self._header = QWidget()
        self._header.setStyleSheet("background:#FFFFFF;border-bottom:1px solid #E0E0E0;")
        self._header.setFixedHeight(44)
        hrow = QHBoxLayout(self._header)
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
        # Dark mode toggle
        self._dark_btn = QToolButton()
        self._dark_btn.setText("\U0001f319")
        self._dark_btn.setCheckable(True)
        self._dark_btn.setToolTip("Toggle dark mode")
        self._dark_btn.setStyleSheet(
            "QToolButton{border:none;font-size:16px;padding:2px 6px;"
            "background:transparent;border-radius:4px;}"
            "QToolButton:hover{background:#F0F0F0;}"
            "QToolButton:checked{background:#2A2A2A;}"
        )
        self._dark_btn.toggled.connect(self._toggle_dark)
        hrow.addWidget(self._dark_btn)

        # Debug drawer toggle button (only in debug_mode)
        if self._debug_mode and self._debug_drawer is not None:
            self._debug_btn = QToolButton()
            self._debug_btn.setText("🛠")
            self._debug_btn.setToolTip("Toggle debug drawer (Ctrl+Shift+D)")
            self._debug_btn.setStyleSheet(
                "QToolButton{border:none;font-size:16px;padding:2px 6px;"
                "background:transparent;border-radius:4px;}"
                "QToolButton:hover{background:#F0F0F0;}"
            )
            self._debug_btn.clicked.connect(self._toggle_debug_drawer)
            hrow.addWidget(self._debug_btn)

        layout.addWidget(self._header)

        # Debug drawer (hidden by default, inserted between header and chat)
        if self._debug_mode and self._debug_drawer is not None:
            self._debug_drawer.setParent(root)
            self._debug_drawer.hide()
            layout.addWidget(self._debug_drawer)

        # Chat widget (takes remaining space)
        self._chat = ChatWidget(debug_mode=self._debug_mode, parent=root)
        layout.addWidget(self._chat, stretch=1)

        # Wire ConfirmBar signals
        self._chat._confirm_bar.approved.connect(self._execute_confirmed)
        self._chat._confirm_bar.rejected.connect(self._on_confirm_rejected)
        self._chat._confirm_bar.edit_requested.connect(self._handle_confirmation)

        # Input row
        self._input_bar = QWidget()
        self._input_bar.setStyleSheet(
            "background:#FFFFFF;border-top:1px solid #E0E0E0;"
        )
        self._input_bar.setFixedHeight(52)
        row = QHBoxLayout(self._input_bar)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Describe your task…")
        self._input.returnPressed.connect(self._handle_submit)
        self._input.setStyleSheet(
            "QLineEdit{border:1px solid #E0E0E0;border-radius:18px;"
            "padding:6px 14px;font-size:13px;background:#F9F9F9;color:#212121;}"
            "QLineEdit:focus{border-color:#FF6347;background:white;}"
        )
        row.addWidget(self._input)

        # Kill path 1: in-app stop button (hidden when not running)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        self._stop_btn.clicked.connect(self._handle_stop)
        self._stop_btn.setStyleSheet(
            "QPushButton{background:#FFEBEE;color:#C62828;"
            "border:1px solid #FFCDD2;border-radius:16px;"
            "padding:6px 16px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#FFCDD2;}"
            "QPushButton:disabled{color:#BDBDBD;background:#F5F5F5;border-color:#E0E0E0;}"
        )
        row.addWidget(self._stop_btn)
        layout.addWidget(self._input_bar)

    def _toggle_dark(self, dark: bool) -> None:
        self._dark = dark
        from qt_material import apply_stylesheet
        theme = "dark_teal.xml" if dark else "light_teal.xml"
        apply_stylesheet(
            QApplication.instance(),
            theme,
            extra={"QTextBrowser": {"background": "transparent"}},
        )
        hbg, hborder = ("#1A1A1A", "#2A2A2A") if dark else ("#FFFFFF", "#E0E0E0")
        ibg, iborder = ("#1A1A1A", "#2A2A2A") if dark else ("#FFFFFF", "#E0E0E0")
        self._header.setStyleSheet(f"background:{hbg};border-bottom:1px solid {hborder};")
        self._input_bar.setStyleSheet(f"background:{ibg};border-top:1px solid {iborder};")
        self._chat.set_dark(dark)
        # Re-apply input state styling for new theme
        self._set_input_state(self._chat.get_state())

    # State → (placeholder, light_bg, border_color)
    _STATE_INPUT_LIGHT = {
        ChatState.IDLE:                   ("Describe your task…",     "#F9F9F9", "#E0E0E0"),
        ChatState.PLANNING:               ("Planning…",               "#FFF3E0", "#FF9800"),
        ChatState.AWAITING_CLARIFICATION: ("Answer to clarify…",      "#E8F5E9", "#4CAF50"),
        ChatState.AWAITING_CONFIRM:       ("or type an amendment…",   "#E3F2FD", "#1976D2"),
        ChatState.EXECUTING:              ("Executing…",              "#E8EAF6", "#3F51B5"),
        ChatState.DONE:                   ("Describe your next task…","#F9F9F9", "#E0E0E0"),
        ChatState.ERROR:                  ("Describe your task…",     "#FFEBEE", "#F44336"),
    }
    _STATE_INPUT_DARK = {
        ChatState.IDLE:                   ("Describe your task…",     "#2A2A2A", "#3A3A3A"),
        ChatState.PLANNING:               ("Planning…",               "#2A1E00", "#FF9800"),
        ChatState.AWAITING_CLARIFICATION: ("Answer to clarify…",      "#0D2010", "#4CAF50"),
        ChatState.AWAITING_CONFIRM:       ("or type an amendment…",   "#0A1929", "#1976D2"),
        ChatState.EXECUTING:              ("Executing…",              "#0D0D2A", "#3F51B5"),
        ChatState.DONE:                   ("Describe your next task…","#2A2A2A", "#3A3A3A"),
        ChatState.ERROR:                  ("Describe your task…",     "#2D0A0A", "#F44336"),
    }

    def _set_input_state(self, state: ChatState) -> None:
        """Update input bar placeholder and border color to reflect current state."""
        table = self._STATE_INPUT_DARK if self._dark else self._STATE_INPUT_LIGHT
        placeholder, bg, border = table.get(state, ("Describe your task…", "#F9F9F9", "#E0E0E0"))
        fg = "#E0E0E0" if self._dark else "#212121"
        self._input.setPlaceholderText(placeholder)
        self._input.setStyleSheet(
            f"QLineEdit{{border:1px solid {border};border-radius:18px;"
            f"padding:6px 14px;font-size:13px;background:{bg};color:{fg};}}"
            f"QLineEdit:focus{{border-color:{border};background:{'#1A1A1A' if self._dark else 'white'};}}"
        )

    def _wire_kill_paths(self) -> None:
        # Kill path 2: global hotkey Ctrl+Shift+Q
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+Q"), self)
        shortcut.activated.connect(self._handle_emergency_stop)

        # Debug drawer shortcut (only in debug_mode)
        if self._debug_mode and self._debug_drawer is not None:
            debug_shortcut = QShortcut(QKeySequence("Ctrl+Shift+D"), self)
            debug_shortcut.activated.connect(self._toggle_debug_drawer)

    # ------------------------------------------------------------------
    # Debug drawer
    # ------------------------------------------------------------------

    def _toggle_debug_drawer(self) -> None:
        if self._debug_drawer is None:
            return
        self._refresh_debug_drawer()
        self._debug_drawer.setVisible(not self._debug_drawer.isVisible())

    def _refresh_debug_drawer(self) -> None:
        if self._debug_drawer is None:
            return
        progress = self._bridge.query_progress() if self._bridge else None
        self._debug_drawer.update(
            state=self._chat.get_state(),
            pending_specs=self._pending_specs,
            pending_request=self._pending_request,
            progress=progress,
        )

    # ------------------------------------------------------------------
    # Public API (used by run_app and tests)
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def log(self, message: str) -> None:
        if self._debug_mode:
            self._chat.add_system_note(message)

    def set_running(self, running: bool) -> None:
        if running:
            self._stop_btn.show()
            self._stop_btn.setEnabled(True)
        else:
            self._stop_btn.setEnabled(False)
            self._stop_btn.hide()
        state = self._chat.get_state()
        if not running and state not in (ChatState.IDLE, ChatState.DONE, ChatState.ERROR):
            self._chat.set_state(ChatState.IDLE)
            self._input.setEnabled(True)
            self._set_input_state(ChatState.IDLE)
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
        elif state == ChatState.AWAITING_CLARIFICATION:
            self._handle_clarification_answer(text)
        elif state in (ChatState.IDLE, ChatState.DONE, ChatState.ERROR):
            self._handle_new_task(text)

    def _handle_new_task(self, task: str) -> None:
        self._pending_request = task
        self._chat.add_user_message(task)
        self._chat.set_state(ChatState.PLANNING)
        self._input.setEnabled(False)
        self._set_input_state(ChatState.PLANNING)
        self.set_status("Planning…")
        self._stop_btn.show()
        self._stop_btn.setEnabled(True)

        if not self._bridge:
            self._chat.add_ai_message(
                "No AI bridge connected. Please check your configuration.",
                thought_prompt="Bridge unavailable.",
            )
            self._chat.set_state(ChatState.ERROR)
            self._input.setEnabled(True)
            self._set_input_state(ChatState.ERROR)
            self._stop_btn.setEnabled(False)
            self._stop_btn.hide()
            return

        # Spin the indicator while the clarification check runs (fast).
        # If the task is clear, _on_clarification_clear will start the thinking
        # stream + planning. If vague, _on_clarification_needed will ask a question.
        self._chat.thinking.set_mode("planning")
        self._chat.thinking.start()
        self._check_clarification_async(task)

    def _start_planning_phase(self) -> None:
        """Start thinking stream + plan_only after clarification is resolved."""
        self._set_input_state(ChatState.PLANNING)
        self.set_status("Planning…")
        self._start_thinking_stream(self._pending_request)
        relay = self._planning_relay
        self._bridge.plan_only(
            user_request=self._pending_request,
            on_planned=lambda specs: relay.planned.emit(specs),
            on_error=lambda err: relay.error.emit(err),
        )

    def _check_clarification_async(self, task: str) -> None:
        """Ask the LLM if the task needs clarification. Fires relay signal with result."""
        import threading
        relay = self._clarification_relay
        settings = self._settings

        def _run() -> None:
            try:
                import asyncio
                import json as _json
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.llm.base import LLMMessage

                if not settings:
                    relay.clear.emit()
                    return

                # Use the fast worker model (flash-lite) with a tight timeout so the
                # clarification check never meaningfully delays the planning phase.
                provider = GeminiProvider(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_worker_model,
                )
                prompt = (
                    f'Task: "{task}"\n\n'
                    "Step 1 — classify the intent:\n"
                    '- "automate": user wants to perform an action on their computer '
                    "(open apps, click UI, run commands, browse the web, manage files, etc.)\n"
                    '- "consult": user wants advice or discussion about automation or computer '
                    "tasks, without actually executing anything\n"
                    '- "chat": general conversation, creative writing, factual questions, '
                    "or anything unrelated to computer automation\n\n"
                    "Step 2 — if intent is 'automate', decide if clarification is needed.\n"
                    "Be EXTREMELY conservative — nearly all tasks are clear enough.\n"
                    "Do NOT ask about preferences, which standard app to use, or whether "
                    "the user is sure.\n"
                    "DO ask only if the core action is genuinely ambiguous.\n\n"
                    "Respond with JSON ONLY — one of:\n"
                    '{"intent": "chat"}\n'
                    '{"intent": "consult"}\n'
                    '{"intent": "automate", "needs_clarification": false}\n'
                    '{"intent": "automate", "needs_clarification": true, "question": "..."}'
                )
                loop = asyncio.new_event_loop()
                try:
                    resp = loop.run_until_complete(
                        provider.complete(
                            [LLMMessage(role="user", content=prompt)],
                            timeout=8.0,  # tight — if slow, skip clarification
                        )
                    )
                    raw = resp.content.strip()
                    # Strip markdown fences if present
                    if raw.startswith("```"):
                        parts = raw.split("```")
                        raw = parts[1] if len(parts) > 1 else raw
                        if raw.startswith("json"):
                            raw = raw[4:].strip()
                    data = _json.loads(raw)
                    intent = data.get("intent", "automate")
                    if intent in ("chat", "consult"):
                        relay.direct_response.emit(intent, task)
                    elif data.get("needs_clarification") and data.get("question"):
                        relay.question.emit(str(data["question"]))
                    else:
                        relay.clear.emit()
                except Exception:
                    relay.clear.emit()  # on any error, just proceed without clarifying
                finally:
                    loop.close()
            except Exception:
                relay.clear.emit()

        threading.Thread(target=_run, daemon=True, name="trinity-clarification").start()

    def _on_clarification_needed(self, question: str) -> None:
        """Task is vague — ask the user a clarifying question."""
        self._chat.thinking.stop()
        self._chat.add_ai_message(
            question,
            thought_prompt="Clarification needed before planning.",
        )
        self._chat.set_state(ChatState.AWAITING_CLARIFICATION)
        self._input.setEnabled(True)
        self._set_input_state(ChatState.AWAITING_CLARIFICATION)
        self.set_status("Awaiting clarification")

    def _on_clarification_clear(self) -> None:
        """Task is specific enough — proceed to planning."""
        self._start_planning_phase()

    def _on_direct_response(self, intent: str, task: str) -> None:
        """Task is chat or consult — stream a direct answer, skip planning entirely."""
        self._chat.thinking.stop()

        if intent == "consult":
            system = (
                "You are Trinity Pilot, a desktop automation advisor. "
                "Give helpful advice about automation, workflows, and computer tasks. "
                "You can discuss strategies and explain concepts, but you are not executing anything right now."
            )
            prompt = f'The user asked: "{task}"\n\nRespond as an automation consultant.'
        else:
            system = (
                "You are Trinity Pilot, a helpful AI assistant. "
                "Answer the user conversationally and directly."
            )
            prompt = f'The user asked: "{task}"\n\nRespond helpfully.'

        self._chat.start_bubble_stream()

        if not self._settings:
            self._chat.set_state(ChatState.DONE)
            self._input.setEnabled(True)
            self._set_input_state(ChatState.DONE)
            self._stop_btn.setEnabled(False)
            self._stop_btn.hide()
            self.set_status("Ready")
            return

        self._stream_worker = StreamWorker(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_planner_model,
            prompt=prompt,
            system=system,
            parent=self,
        )
        self._stream_worker.chunk_received.connect(self._chat.on_bubble_stream_chunk)
        self._stream_worker.stream_done.connect(self._on_direct_response_done)
        self._stream_worker.stream_error.connect(self._on_thinking_stream_error)
        self._stream_worker.start()
        self.set_status("Responding…")

    def _on_direct_response_done(self, _full_text: str) -> None:
        self._chat.set_state(ChatState.DONE)
        self._input.setEnabled(True)
        self._set_input_state(ChatState.DONE)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        self.set_status("Ready")

    def _handle_clarification_answer(self, answer: str) -> None:
        """User answered the clarification question — enrich request and plan."""
        self._chat.add_user_message(answer)
        self._pending_request = f"{self._pending_request}. Additional context: {answer}"
        self._chat.set_state(ChatState.PLANNING)
        self._input.setEnabled(False)
        self._set_input_state(ChatState.PLANNING)
        self.set_status("Planning…")
        self._chat.thinking.start()
        self._start_planning_phase()

    def _handle_confirmation(self, text: str) -> None:
        """Handle free-text confirmation input or edit_requested signal text."""
        lower = text.lower().strip()
        self._chat.hide_confirm_bar()
        if lower in _CONFIRM_YES:
            self._chat.add_user_message(text)
            self._execute_confirmed()
        elif lower in _CONFIRM_NO:
            self._chat.add_user_message(text)
            self._on_confirm_rejected()
        else:
            # Treat as amended request — re-plan
            amended = f"{self._pending_request}. {text}"
            self._chat.add_user_message(text)
            self._chat.add_ai_message(
                f"Sure, I'll adjust the plan: \"{text}\". Re-planning now…",
                thought_prompt="User requested amendments.",
            )
            self._handle_new_task(amended)

    def _on_confirm_rejected(self) -> None:
        """Cancel the current plan, return to IDLE."""
        self._chat.hide_confirm_bar()
        self._chat.add_ai_message(
            "Got it, cancelling. Let me know when you want to try again.",
            thought_prompt="User cancelled.",
        )
        self._chat.set_state(ChatState.IDLE)
        self._input.setEnabled(True)
        self._set_input_state(ChatState.IDLE)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        self.set_status("Ready")

    def _execute_confirmed(self) -> None:
        self._chat.hide_confirm_bar()
        self._chat.thinking.set_mode("executing")
        self._chat.thinking.start()
        self._chat.add_ai_message(
            "Starting execution now. I'll keep you updated as each objective completes.",
            thought_prompt="User confirmed plan. Starting local orchestration.",
        )
        task_id = self._bridge.start_task(
            user_request=self._pending_request,
            on_log=self.log,
            on_status=lambda s: self.set_status(
                {"running": "Executing…", "completed": "Done",
                 "failed": "Error", "cancelled": "Cancelled"}.get(s, s.capitalize())
            ),
            on_done=self._on_task_done,
            objectives=self._pending_specs,
        ) if self._bridge else None

        if task_id:
            self._chat.start_task(
                task_id=task_id,
                specs=self._pending_specs,
                start_time=time.monotonic(),
            )
        self._input.setEnabled(False)
        self._set_input_state(ChatState.EXECUTING)
        self.set_status("Executing…")

    # ------------------------------------------------------------------
    # Task lifecycle callbacks
    # ------------------------------------------------------------------

    def _on_planning_done(self, specs: list) -> None:
        self._chat.thinking.stop()
        self._pending_specs = list(specs)
        self._chat.show_objectives_card(self._pending_specs)
        self._chat.set_state(ChatState.AWAITING_CONFIRM)
        self._chat.show_confirm_bar()
        self._input.setEnabled(True)
        self._set_input_state(ChatState.AWAITING_CONFIRM)
        self.set_status("Awaiting confirmation")

    def _on_planning_error(self, error: str) -> None:
        self._chat.thinking.stop()
        self._chat.add_ai_message(
            f"Sorry, I couldn't plan your task: {error}",
            thought_prompt=f"Planning error: {error}",
        )
        self._chat.set_state(ChatState.ERROR)
        self._input.setEnabled(True)
        self._set_input_state(ChatState.ERROR)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        self.set_status("Planning failed")

    def _on_task_done(self, final_result: dict) -> None:
        self._chat.thinking.stop()
        if isinstance(final_result, dict):
            final_status = str(final_result.get("status", "unknown"))
            workflow_results = final_result.get("results") or {}
            error_msg = final_result.get("error", "")
            tb_msg = final_result.get("traceback", "")
            if error_msg:
                self.log(f"[ERROR] {error_msg}")
            # Surface crash/error prominently in chat.
            if final_status in ("crashed", "failed") and error_msg:
                from trinity_pilot.__main__ import CRASHES_DIR
                hint = f"\n\nCrash report saved to: `crashes/`" if CRASHES_DIR.exists() else ""
                self._chat.add_ai_message(
                    f"❌ Task crashed: **{error_msg}**{hint}",
                    thought_prompt=tb_msg or error_msg,
                )
        else:
            final_status = str(final_result)
            workflow_results = {}
            error_msg = ""

        results = {}
        for i, spec in enumerate(self._pending_specs):
            obj_id = spec.get("objective_id", f"obj_{i}")
            entry = dict(workflow_results.get(obj_id, {"status": "not_run"}))
            status = str(entry.get("status", "unknown"))
            if status.startswith("attempt_") and status.endswith("_failed"):
                entry["status"] = "failed"
            results[obj_id] = entry

        self._chat.show_completion(
            status=final_status,
            results=results,
        )
        terminal = ChatState.DONE if final_status == "completed" else ChatState.ERROR
        self._chat.set_state(terminal)
        self._input.setEnabled(True)
        self._set_input_state(terminal)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        _done_labels = {"completed": "Done", "failed": "Error", "cancelled": "Cancelled", "crashed": "Crashed"}
        self.set_status(_done_labels.get(final_status, f"Finished: {final_status}"))

        # Show worker finish-summaries directly as an AI reply.
        # Workers already produce descriptive summaries in their finish() call —
        # no extra LLM needed, just surface them.
        if final_status == "completed":
            summaries: list[str] = []
            for i, spec in enumerate(self._pending_specs):
                obj_id = spec.get("objective_id", f"obj_{i}")
                entry = workflow_results.get(obj_id, {})
                s = entry.get("summary", "") or entry.get("evidence", {}).get("worker_result_summary", "")
                if s:
                    summaries.append(s)
            if summaries:
                reply = "\n\n".join(summaries) if len(summaries) > 1 else summaries[0]
                self._chat.add_ai_message(reply, thought_prompt="Worker finish summaries.")

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


def _install_qt_exception_hook(window_ref: "list[MainWindow]") -> None:
    """Catch unhandled exceptions in Qt slots — PySide6 swallows them silently.

    Writes crash JSON to crashes/, shows a QMessageBox so the user sees the
    error before the process exits, then re-raises so the normal exit path runs.
    """
    import traceback
    from trinity_pilot.__main__ import _write_crash, _ensure_crashes_dir

    _orig_hook = sys.excepthook

    def _qt_hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_path = _write_crash("qt-slot", msg, _ensure_crashes_dir())

        # Try to show the error in the chat widget if window is available.
        try:
            win = window_ref[0] if window_ref else None
            if win and hasattr(win, "_chat"):
                hint = f"See crashes/ folder for full trace." if crash_path else ""
                win._chat.add_ai_message(
                    f"⚠️ Unhandled error: {exc_type.__name__}: {exc_value}\n{hint}",
                    thought_prompt="crash",
                )
                win.set_status("Error")
        except Exception:
            pass

        # Fallback: Qt message box so user is never left with a silent close.
        try:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox()
            box.setWindowTitle("Trinity Pilot — Unexpected Error")
            box.setIcon(QMessageBox.Icon.Critical)
            box.setText(f"<b>{exc_type.__name__}</b>: {exc_value}")
            box.setDetailedText(msg)
            if crash_path:
                box.setInformativeText(f"Crash report saved to:\n{crash_path}")
            box.exec()
        except Exception:
            pass

        _orig_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _qt_hook


def run_app(test_mode: bool = False) -> None:
    from trinity_pilot.config import Settings
    from trinity_pilot.ui.bridge import WorkflowBridge

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    settings = Settings.from_env()

    bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)

    window = MainWindow(debug_mode=settings.debug_mode)
    window.set_bridge(bridge)
    window.set_settings(settings)
    window.log("[SYSTEM] Local orchestrator ready.")

    _window_ref: list[MainWindow] = [window]
    _install_qt_exception_hook(_window_ref)

    # qt-material must import after PySide6
    from qt_material import apply_stylesheet
    apply_stylesheet(
        app,
        theme="light_teal.xml",
        extra={"QTextBrowser": {"background": "transparent"}},
    )
    # _dark stays False (default), toggle stays unchecked — user can switch to dark

    window.show()
    sys.exit(app.exec())
