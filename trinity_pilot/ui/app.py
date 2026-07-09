from __future__ import annotations

import json
import signal
import sys
import time
from typing import Any

import pyautogui
from PySide6.QtCore import (
    QEasingCurve, QObject, QPropertyAnimation,
    QSequentialAnimationGroup, QTimer, Signal,
)
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
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

from trinity_pilot.ui.chat_widget import ChatState, ChatWidget
from trinity_pilot.ui.stream_worker import StreamWorker
from trinity_pilot.ui.theme import (
    STATE_INPUT_BORDER, STATE_PLACEHOLDER, STATE_STRIPE,
    apply_app_qss, tok,
)

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
    def __init__(self, debug_mode: bool = False, mode: str = "multi") -> None:
        super().__init__()
        self._bridge: Any = None
        self._debug_mode = debug_mode
        self._mode = mode  # "multi" or "single_agent"
        self._dark = False
        self._settings: Any = None
        self._stream_worker: StreamWorker | None = None
        self._pending_specs: list[dict] = []
        self._pending_request: str = ""
        self._status_anim: QSequentialAnimationGroup | None = None
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

        # ── State stripe — 3px accent line at top of window ──────────────
        self._stripe = QWidget()
        self._stripe.setFixedHeight(3)
        self._stripe_effect = QGraphicsOpacityEffect(self._stripe)
        self._stripe.setGraphicsEffect(self._stripe_effect)
        self._stripe_anim: QSequentialAnimationGroup | None = None
        self._stripe_pending_color: str | None = None
        self._apply_stripe_color(tok("stripe_idle", self._dark))
        layout.addWidget(self._stripe)

        # ── Header bar ───────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(44)
        self._apply_header_style()
        hrow = QHBoxLayout(self._header)
        hrow.setContentsMargins(14, 0, 10, 0)
        hrow.setSpacing(6)

        # Brand mark
        title = QLabel("Trinity Pilot")
        title.setStyleSheet(
            "color:#FF6347;font-weight:800;font-size:15px;letter-spacing:-0.3px;"
        )
        hrow.addWidget(title)
        hrow.addStretch()

        # Status label
        self._status_label = QLabel("Ready")
        self._apply_status_style()
        hrow.addWidget(self._status_label)

        if self._debug_mode:
            dbg = QLabel("DEBUG")
            dbg.setStyleSheet(
                "color:#FF6347;font-size:10px;font-weight:700;"
                "background:#FFF0ED;padding:2px 8px;border-radius:8px;"
            )
            hrow.addWidget(dbg)

        # Dark mode toggle
        self._dark_btn = QToolButton()
        self._dark_btn.setText("🌙")
        self._dark_btn.setCheckable(True)
        self._dark_btn.setToolTip("Toggle dark mode")
        self._dark_btn.toggled.connect(self._toggle_dark)
        hrow.addWidget(self._dark_btn)

        if self._debug_mode and self._debug_drawer is not None:
            self._debug_btn = QToolButton()
            self._debug_btn.setText("🛠")
            self._debug_btn.setToolTip("Toggle debug drawer (Ctrl+Shift+D)")
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

        # ── Input bar ────────────────────────────────────────────────────
        self._input_bar = QWidget()
        self._input_bar.setFixedHeight(56)
        self._apply_input_bar_style()
        row = QHBoxLayout(self._input_bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Describe your task…")
        self._input.returnPressed.connect(self._handle_submit)
        self._apply_input_style(ChatState.IDLE)
        row.addWidget(self._input)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        self._stop_btn.clicked.connect(self._handle_stop)
        self._apply_stop_btn_style()
        row.addWidget(self._stop_btn)
        layout.addWidget(self._input_bar)

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _t(self, name: str) -> str:
        return tok(name, self._dark)

    def _apply_header_style(self) -> None:
        bg = self._t("surface")
        border = self._t("border")
        self._header.setStyleSheet(
            f"background:{bg};border-bottom:1px solid {border};"
        )

    def _apply_status_style(self) -> None:
        self._status_label.setStyleSheet(
            f"color:{self._t('text_muted')};font-size:12px;"
        )

    def _apply_input_bar_style(self) -> None:
        bg = self._t("surface")
        border = self._t("border")
        self._input_bar.setStyleSheet(
            f"background:{bg};border-top:1px solid {border};"
        )

    def _apply_input_style(self, state: ChatState) -> None:
        state_name = state.name
        border_tok = STATE_INPUT_BORDER.get(state_name, "input_border")
        border = self._t(border_tok)
        bg = self._t("input_bg")
        fg = self._t("text")
        placeholder_text = STATE_PLACEHOLDER.get(state_name, "Describe your task…")
        self._input.setPlaceholderText(placeholder_text)
        self._input.setStyleSheet(
            f"QLineEdit{{"
            f"border:1.5px solid {border};border-radius:20px;"
            f"padding:7px 16px;font-size:13px;background:{bg};color:{fg};"
            f"}}"
            f"QLineEdit:focus{{"
            f"border:2px solid {border};"
            f"background:{self._t('surface')};"
            f"}}"
        )

    def _apply_stop_btn_style(self) -> None:
        bg = self._t("btn_stop_bg")
        fg = self._t("btn_stop_fg")
        brd = self._t("btn_stop_brd")
        self._stop_btn.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};"
            f"border:1px solid {brd};border-radius:18px;"
            f"padding:7px 18px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{brd};}}"
            f"QPushButton:disabled{{opacity:0.4;}}"
        )

    def _apply_stripe_color(self, color: str) -> None:
        self._stripe.setStyleSheet(f"background:{color};")

    def _animate_stripe(self, color: str) -> None:
        """Crossfade the header stripe to a new color."""
        if self._stripe_anim:
            self._stripe_anim.stop()
        self._stripe_pending_color = color

        seq = QSequentialAnimationGroup(self._stripe)
        out = QPropertyAnimation(self._stripe_effect, b"opacity", seq)
        out.setDuration(80)
        out.setStartValue(1.0)
        out.setEndValue(0.0)

        def _swap():
            if self._stripe_pending_color:
                self._apply_stripe_color(self._stripe_pending_color)
                self._stripe_pending_color = None

        out.finished.connect(_swap)

        inn = QPropertyAnimation(self._stripe_effect, b"opacity", seq)
        inn.setDuration(180)
        inn.setStartValue(0.0)
        inn.setEndValue(1.0)
        inn.setEasingCurve(QEasingCurve.Type.OutCubic)

        seq.addAnimation(out)
        seq.addAnimation(inn)
        seq.start()
        self._stripe_anim = seq

    def _toggle_dark(self, dark: bool) -> None:
        self._dark = dark
        # Rebuild app-level QSS (replaces qt_material entirely)
        apply_app_qss(QApplication.instance(), dark=dark, scale=self._ui_scale())
        # Refresh all themed components
        self._apply_header_style()
        self._apply_status_style()
        self._apply_input_bar_style()
        self._apply_stop_btn_style()
        current_state = self._chat.get_state()
        self._apply_input_style(current_state)
        stripe_tok = STATE_STRIPE.get(current_state.name, "stripe_idle")
        self._apply_stripe_color(self._t(stripe_tok))
        self._chat.set_dark(dark)

    def _ui_scale(self) -> float:
        """Compute text scale factor based on window height. Base = 800px → 1.0."""
        h = self.height()
        if h <= 0:
            return 1.0
        return max(0.75, min(1.6, h / 800.0))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        scale = self._ui_scale()
        self._chat.set_scale(scale)
        apply_app_qss(QApplication.instance(), dark=self._dark, scale=scale)

    def _set_input_state(self, state: ChatState) -> None:
        """Update input styling and header stripe for the new state."""
        self._apply_input_style(state)
        stripe_tok = STATE_STRIPE.get(state.name, "stripe_idle")
        self._animate_stripe(self._t(stripe_tok))

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
        if self._status_label.text() == text:
            return
        if self._status_anim:
            self._status_anim.stop()
            self._status_anim = None

        effect = QGraphicsOpacityEffect(self._status_label)
        self._status_label.setGraphicsEffect(effect)

        seq = QSequentialAnimationGroup(self._status_label)

        out = QPropertyAnimation(effect, b"opacity", seq)  # parent=seq prevents GC
        out.setDuration(80)
        out.setStartValue(1.0)
        out.setEndValue(0.0)
        out.finished.connect(lambda: self._status_label.setText(text))

        inn = QPropertyAnimation(effect, b"opacity", seq)  # parent=seq prevents GC
        inn.setDuration(120)
        inn.setStartValue(0.0)
        inn.setEndValue(1.0)
        inn.setEasingCurve(QEasingCurve.Type.OutCubic)
        seq.addAnimation(out)
        seq.addAnimation(inn)
        seq.start()
        self._status_anim = seq

    def log(self, message: str) -> None:
        from trinity_pilot.telemetry.trace import emit

        emit(
            "app.py:log",
            "bridge_log_message",
            {"message": message},
            span="bridge",
        )
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
        from trinity_pilot._agent_debug import agent_dbg

        agent_dbg(
            "app.py:_handle_new_task",
            "new_task_submitted",
            {"task_preview": task[:120], "mode": self._mode},
            hypothesis_id="H2-clarification-hang",
        )
        if self._mode == "single_agent":
            self._handle_new_task_single_agent(task)
            return

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

    def _handle_new_task_single_agent(self, task: str) -> None:
        """Single-agent mode: skip clarification and planning, execute immediately."""
        self._pending_request = task
        self._pending_specs = []
        self._chat.add_user_message(task)
        self._chat.set_state(ChatState.EXECUTING)
        self._input.setEnabled(False)
        self._set_input_state(ChatState.EXECUTING)
        self.set_status("Executing…")
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
            self.set_status("Error")
            return

        self._bridge.start_task_single_agent(
            user_request=task,
            on_log=self.log,
            on_status=lambda s: None,
            on_done=self._on_single_agent_done,
        )

    def _on_single_agent_done(self, result: dict) -> None:
        self._chat.thinking.stop()
        if isinstance(result, dict):
            final_status = result.get("status", "failed")
            summary = result.get("single_agent_summary", "")
            error_msg = result.get("error", "")
            if error_msg and final_status in ("crashed", "failed"):
                self._chat.add_ai_message(
                    f"Task failed: {error_msg}",
                    thought_prompt=result.get("traceback", error_msg),
                )
        else:
            final_status = "failed"
            summary = ""

        terminal = ChatState.DONE if final_status == "completed" else ChatState.ERROR
        self._chat.set_state(terminal)
        self._input.setEnabled(True)
        self._set_input_state(terminal)
        self._stop_btn.setEnabled(False)
        self._stop_btn.hide()
        _done_labels = {
            "completed": "Done",
            "failed": "Failed",
            "cancelled": "Cancelled",
            "crashed": "Crashed",
        }
        self.set_status(_done_labels.get(final_status, f"Finished: {final_status}"))

        if summary and final_status == "completed":
            self._chat.add_ai_message(summary, thought_prompt="Single-agent finish summary.")

    def _start_planning_phase(self) -> None:
        """Start thinking stream + plan_only after clarification is resolved."""
        from trinity_pilot._agent_debug import agent_dbg

        agent_dbg(
            "app.py:_start_planning_phase",
            "planning_phase_start",
            {"request_preview": (self._pending_request or "")[:120]},
            hypothesis_id="H1-planner-hang",
        )
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
        import re
        import threading
        relay = self._clarification_relay

        # Fast sync pre-check — handle obvious chat/greetings without any LLM call.
        _GREETING_RE = re.compile(
            r'^(hi|hello|hey|sup|yo|howdy|greetings|good (morning|afternoon|evening|night)|'
            r'bye|goodbye|ciao|salut|bonjour|hola|thanks|thank you|cheers)[\s!?.]*$',
            re.IGNORECASE,
        )
        if _GREETING_RE.match(task.strip()):
            relay.direct_response.emit("chat", task)
            return

        # Fast sync pre-check — numbered step lists or URLs are unambiguously
        # automation requests. Skip the LLM intent classifier entirely for these:
        # it's a tight-timeout (8s) call on a fast/lite model that can misclassify
        # a long multi-step task as "chat"/"consult", silently skipping planning.
        _AUTOMATE_SIGNAL_RE = re.compile(r'(\d+[\).]\s|https?://)', re.IGNORECASE)
        if _AUTOMATE_SIGNAL_RE.search(task):
            from trinity_pilot._agent_debug import agent_dbg

            agent_dbg(
                "app.py:_check_clarification_async",
                "clarification_fast_automate_clear",
                {"task_preview": task[:80]},
                hypothesis_id="H2-clarification-hang",
            )
            relay.clear.emit()
            return

        settings = self._settings

        def _run() -> None:
            import time as _time
            from trinity_pilot._agent_debug import agent_dbg

            t0 = _time.monotonic()
            agent_dbg(
                "app.py:_check_clarification_async",
                "clarification_thread_start",
                {"task_preview": task[:120]},
                hypothesis_id="H2-clarification-hang",
            )
            try:
                import asyncio
                import json as _json
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.llm.base import LLMMessage

                if not settings:
                    # No config — can't automate; respond as chat.
                    agent_dbg(
                        "app.py:_check_clarification_async",
                        "no_settings_direct_chat",
                        {"elapsed_ms": int((_time.monotonic() - t0) * 1000)},
                        hypothesis_id="H2-clarification-hang",
                    )
                    relay.direct_response.emit("chat", task)
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
                    "Do NOT ask about preferences, which standard app to use, or whether "
                    "the user is sure.\n"
                    "DO ask if ANY of these are true:\n"
                    "  - The goal has no specific action (e.g. 'do something useful on my computer')\n"
                    "  - The target is completely undefined (e.g. 'help me with my files' — which files?)\n"
                    "  - There are two+ mutually exclusive interpretations of equal likelihood\n"
                    "Otherwise proceed — most tasks are specific enough.\n\n"
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
                        agent_dbg(
                            "app.py:_check_clarification_async",
                            "clarification_direct_response",
                            {
                                "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                                "intent": intent,
                            },
                            hypothesis_id="H2-clarification-hang",
                        )
                        relay.direct_response.emit(intent, task)
                    elif data.get("needs_clarification") and data.get("question"):
                        agent_dbg(
                            "app.py:_check_clarification_async",
                            "clarification_question",
                            {
                                "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                                "question_preview": str(data.get("question", ""))[:120],
                            },
                            hypothesis_id="H2-clarification-hang",
                        )
                        relay.question.emit(str(data["question"]))
                    else:
                        agent_dbg(
                            "app.py:_check_clarification_async",
                            "clarification_clear",
                            {
                                "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                                "intent": intent,
                            },
                            hypothesis_id="H2-clarification-hang",
                        )
                        relay.clear.emit()
                except Exception as exc:
                    agent_dbg(
                        "app.py:_check_clarification_async",
                        "clarification_llm_error_default_clear",
                        {
                            "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                            "error": str(exc)[:300],
                        },
                        hypothesis_id="H2-clarification-hang",
                    )
                    # LLM classification failed — default to planning so automation
                    # requests still work; chat messages hit the pre-classifier above.
                    relay.clear.emit()
                finally:
                    loop.close()
            except Exception as exc:
                agent_dbg(
                    "app.py:_check_clarification_async",
                    "clarification_outer_error_default_clear",
                    {
                        "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                        "error": str(exc)[:300],
                    },
                    hypothesis_id="H2-clarification-hang",
                )
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
        from trinity_pilot._agent_debug import agent_dbg

        agent_dbg(
            "app.py:_on_clarification_clear",
            "clarification_cleared_on_main_thread",
            {},
            hypothesis_id="H2-clarification-hang",
        )
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
        self._chat.on_bubble_stream_done()
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
                 "failed": "Failed", "cancelled": "Cancelled"}.get(s, s.capitalize())
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
        from trinity_pilot._agent_debug import agent_dbg

        agent_dbg(
            "app.py:_on_planning_done",
            "planning_done_on_main_thread",
            {
                "n_specs": len(specs),
                "objective_ids": [s.get("objective_id") for s in specs if isinstance(s, dict)],
            },
            hypothesis_id="H3-qt-relay",
        )
        self._chat.thinking.stop()
        self._pending_specs = list(specs)
        self._chat.show_objectives_card(self._pending_specs)
        self._chat.set_state(ChatState.AWAITING_CONFIRM)
        self._chat.show_confirm_bar()
        self._input.setEnabled(True)
        self._set_input_state(ChatState.AWAITING_CONFIRM)
        self.set_status("Awaiting confirmation")

    def _on_planning_error(self, error: str) -> None:
        from trinity_pilot._agent_debug import agent_dbg

        agent_dbg(
            "app.py:_on_planning_error",
            "planning_error_on_main_thread",
            {"error": error[:500]},
            hypothesis_id="H3-qt-relay",
        )
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
        _done_labels = {"completed": "Done", "failed": "Failed", "cancelled": "Cancelled", "crashed": "Crashed"}
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


def start_http_bridge(window_ref: list[MainWindow], port: int):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import socketserver
    import threading

    class BridgeHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path == "/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                
                win = window_ref[0] if window_ref else None
                status = win._status_label.text() if win else "Unknown"
                last_error = ""
                active_objective_id = ""
                
                if win and win._pending_specs:
                    active_objective_id = win._pending_specs[0].get("objective_id", "")
                
                response = {
                    "status": status,
                    "last_error": last_error,
                    "active_objective_id": active_objective_id,
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            elif self.path == "/run_info":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                win = window_ref[0] if window_ref else None
                response = {
                    "mode": win._mode if win else "unknown",
                    "pending_request": win._pending_request if win else "",
                    "n_pending_specs": len(win._pending_specs) if win else 0,
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        allow_reuse_address = True

    server = None
    for attempt_port in range(port, port + 10):
        try:
            server = ThreadedHTTPServer(("localhost", attempt_port), BridgeHandler)
            print(f"[HTTP Bridge] Listening on http://localhost:{attempt_port}", flush=True)
            break
        except OSError as e:
            print(f"[HTTP Bridge] Port {attempt_port} busy: {e}. Retrying next port...", flush=True)

    if server:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server
    else:
        print("[HTTP Bridge] Failed to bind to any port in range.", flush=True)
        return None


def run_app(test_mode: bool = False, mode: str = "multi", test_port: int | None = None) -> None:
    import os

    from trinity_pilot.config import Settings
    from trinity_pilot.ui.bridge import WorkflowBridge

    if test_mode:
        os.environ.setdefault("TRINITY_TRACE", "1")

    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    settings = Settings.from_env()

    bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)

    window = MainWindow(debug_mode=settings.debug_mode, mode=mode)
    window.set_bridge(bridge)
    window.set_settings(settings)
    window.log("[SYSTEM] Local orchestrator ready.")

    _window_ref: list[MainWindow] = [window]
    _install_qt_exception_hook(_window_ref)

    if test_port is not None:
        start_http_bridge(_window_ref, test_port)

    # Apply base QSS (token-based, no qt_material dependency)
    apply_app_qss(app, dark=False)

    window.show()
    sys.exit(app.exec())
