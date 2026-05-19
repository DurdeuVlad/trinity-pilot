from __future__ import annotations

import time
from enum import Enum, auto
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from trinity_pilot.ui import bubble_renderer as br
from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
from trinity_pilot.ui.thinking_indicator import ThinkingIndicator


class ChatState(Enum):
    IDLE = auto()
    PLANNING = auto()
    AWAITING_CLARIFICATION = auto()
    AWAITING_CONFIRM = auto()
    EXECUTING = auto()
    DONE = auto()
    ERROR = auto()


class _ConfirmBar(QWidget):
    """Inline confirm/reject/edit bar shown after planning completes."""

    approved = Signal()
    rejected = Signal()
    edit_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.apply_dark(False)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        lbl = QLabel("Plan ready:")
        lbl.setStyleSheet("font-size:12px;font-weight:600;")
        layout.addWidget(lbl)

        self._approve_btn = QPushButton("✓ Approve")
        self._approve_btn.setStyleSheet(
            "QPushButton{background:#E8F5E9;color:#2E7D32;"
            "border:1px solid #A5D6A7;border-radius:12px;"
            "padding:4px 14px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#C8E6C9;}"
        )
        self._approve_btn.clicked.connect(self._on_approve)
        layout.addWidget(self._approve_btn)

        self._reject_btn = QPushButton("✗ Reject")
        self._reject_btn.setStyleSheet(
            "QPushButton{background:#FFEBEE;color:#C62828;"
            "border:1px solid #FFCDD2;border-radius:12px;"
            "padding:4px 14px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#FFCDD2;}"
        )
        self._reject_btn.clicked.connect(self._on_reject)
        layout.addWidget(self._reject_btn)

        self._edit_btn = QPushButton("✎ Edit")
        self._edit_btn.setStyleSheet(
            "QPushButton{background:#F5F5F5;color:#424242;"
            "border:1px solid #E0E0E0;border-radius:12px;"
            "padding:4px 14px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#EEEEEE;}"
        )
        self._edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(self._edit_btn)

        self._edit_input = QLineEdit()
        self._edit_input.setPlaceholderText("Describe your changes…")
        self._edit_input.setStyleSheet(
            "QLineEdit{border:1px solid #E0E0E0;border-radius:12px;"
            "padding:4px 10px;font-size:12px;}"
        )
        self._edit_input.setVisible(False)
        self._edit_input.returnPressed.connect(self._on_edit_submit)
        layout.addWidget(self._edit_input, stretch=1)

        layout.addStretch()

    def _on_approve(self) -> None:
        self.approved.emit()
        self.hide()

    def _on_reject(self) -> None:
        self.rejected.emit()
        self.hide()

    def _on_edit(self) -> None:
        self._approve_btn.setVisible(False)
        self._reject_btn.setVisible(False)
        self._edit_btn.setVisible(False)
        self._edit_input.setVisible(True)
        self._edit_input.setFocus()

    def _on_edit_submit(self) -> None:
        text = self._edit_input.text().strip()
        # Reset UI state back to buttons
        self._edit_input.clear()
        self._edit_input.setVisible(False)
        self._approve_btn.setVisible(True)
        self._reject_btn.setVisible(True)
        self._edit_btn.setVisible(True)
        self.edit_requested.emit(text)
        self.hide()

    def apply_dark(self, dark: bool) -> None:
        """Update bar background for dark/light palette."""
        bg = "#1E1E1E" if dark else "#F5F5F5"
        border = "#2A2A2A" if dark else "#E0E0E0"
        self.setStyleSheet(
            f"background:{bg};border-top:1px solid {border};"
        )


class _ThoughtPanel(QWidget):
    """Collapsible AI thought panel shown below the message browser."""

    def __init__(self, debug_mode: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._debug_mode = debug_mode
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 4)
        layout.setSpacing(2)

        self._toggle = QToolButton()
        self._toggle.setText("\U0001f9e0 Thoughts ▸")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(debug_mode)
        self._toggle.toggled.connect(self._on_toggle)
        layout.addWidget(self._toggle)

        self._thought_view = QTextEdit()
        self._thought_view.setReadOnly(True)
        self._thought_view.setFixedHeight(72)
        self._thought_view.setVisible(debug_mode)
        layout.addWidget(self._thought_view)

        if debug_mode:
            self._debug_view: QTextEdit | None = QTextEdit()
            self._debug_view.setReadOnly(True)
            self._debug_view.setFixedHeight(60)
            layout.addWidget(self._debug_view)
        else:
            self._debug_view = None

        self.apply_dark(False)

    def apply_dark(self, dark: bool) -> None:
        from PySide6.QtGui import QColor, QPalette
        bg = "#1A1A1A" if dark else "#FFFFFF"
        border = "#2A2A2A" if dark else "#F0F0F0"
        tv_bg = "#242424" if dark else "#FAFAFA"
        tv_border = "#3A3A3A" if dark else "#E0E0E0"
        tv_fg = "#CCCCCC" if dark else "#555"
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window, QColor(bg))
        p.setColor(QPalette.ColorRole.Base, QColor(tv_bg))
        p.setColor(QPalette.ColorRole.WindowText, QColor(tv_fg))
        self.setPalette(p)
        self.setStyleSheet(
            f"background:{bg};"
            "border-left:3px solid #FF6347;"
            f"border-top:1px solid {border};"
            "margin-left:4px;"
        )
        self._toggle.setStyleSheet(
            "QToolButton{border:none;color:#FF6347;font-size:11px;"
            "font-style:italic;background:transparent;}"
            "QToolButton:hover{color:#FF8A65;}"
        )
        self._thought_view.setStyleSheet(
            f"QTextEdit{{background:{tv_bg};border:1px solid {tv_border};"
            f"border-radius:4px;font-size:11px;color:{tv_fg};padding:4px;}}"
        )
        if self._debug_view:
            self._debug_view.setStyleSheet(
                "QTextEdit{background:#0D0D0D;color:#80CBC4;"
                "font-family:monospace;font-size:10px;padding:4px;border-radius:4px;}"
            )

    def append_chunk(self, chunk: str) -> None:
        cursor = self._thought_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._thought_view.setTextCursor(cursor)
        self._thought_view.ensureCursorVisible()
        if not self._thought_view.isVisible():
            pass  # chunks accumulate even when hidden

    def set_text(self, text: str) -> None:
        self._thought_view.setPlainText(text)

    def set_debug_json(self, text: str) -> None:
        if self._debug_view:
            self._debug_view.setPlainText(text)

    def _on_toggle(self, checked: bool) -> None:
        self._toggle.setText(
            f"\U0001f9e0 Thoughts {'▾' if checked else '▸'}"
        )
        self._thought_view.setVisible(checked)
        if self._debug_view:
            self._debug_view.setVisible(checked)


class ChatWidget(QWidget):
    """Polished chat interface replacing the raw QTextEdit log view."""

    def __init__(
        self,
        debug_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._debug_mode = debug_mode
        self._dark = False
        self._state = ChatState.IDLE
        self._pending_specs: list[dict] = []
        self._task_id: str | None = None
        self._start_time: float = 0.0
        self._bridge: Any = None
        self._current_thought_panel: _ThoughtPanel | None = None
        # Each block is stored as (kind, args) so it can be re-rendered on theme change
        self._message_log: list[tuple[str, tuple]] = []

        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._on_poll)

    def set_bridge(self, bridge: Any) -> None:
        self._bridge = bridge

    def set_dark(self, dark: bool) -> None:
        """Switch the entire chat widget between dark and light mode."""
        self._dark = dark
        from PySide6.QtGui import QColor, QPalette
        browser_bg = "#121212" if dark else "#FAFAFA"
        p = QPalette()
        p.setColor(QPalette.ColorRole.Base, QColor(browser_bg))
        p.setColor(QPalette.ColorRole.Text, QColor("#E0E0E0" if dark else "#212121"))
        self._browser.setPalette(p)
        self._browser.setStyleSheet(
            f"QTextBrowser{{background:{browser_bg};border:none;"
            "font-size:13px;padding:4px 8px;}"
        )
        self._thought_panel.apply_dark(dark)
        self._confirm_bar.apply_dark(dark)
        self._chips.apply_dark(dark)
        self._thinking.apply_dark(dark)
        self._rebuild_html()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Main message browser — renders block-level HTML correctly
        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(False)
        self._browser.setStyleSheet(
            "QTextBrowser{background:#FAFAFA;border:none;"
            "font-size:13px;padding:4px 8px;}"
        )
        root_layout.addWidget(self._browser, stretch=1)

        # Thought panel immediately below chat (visually connected to last AI bubble)
        self._thought_panel = _ThoughtPanel(debug_mode=self._debug_mode, parent=self)
        self._thought_panel.hide()
        root_layout.addWidget(self._thought_panel)

        # Confirm bar (hidden by default, shown after planning)
        self._confirm_bar = _ConfirmBar(self)
        self._confirm_bar.hide()
        root_layout.addWidget(self._confirm_bar)

        # Thinking indicator
        self._thinking = ThinkingIndicator(self)
        root_layout.addWidget(self._thinking)

        # Objective chips
        self._chips = ObjectiveChipsWidget(self)
        root_layout.addWidget(self._chips)

        # Show welcome message on launch
        self._message_log.append(("welcome", ()))
        self._rebuild_html()

    # ------------------------------------------------------------------
    # Public confirm bar API
    # ------------------------------------------------------------------

    def show_confirm_bar(self) -> None:
        """Show the _ConfirmBar below the chat browser."""
        self._confirm_bar.show()

    def hide_confirm_bar(self) -> None:
        """Hide the _ConfirmBar."""
        self._confirm_bar.hide()

    # ------------------------------------------------------------------
    # Public execution step API
    # ------------------------------------------------------------------

    def show_execution_step(self, label: str, status: str, indent_level: int = 0) -> None:
        """Append an execution row to the message log and re-render."""
        self._message_log.append(("exec_step", (label, status, indent_level)))
        self._append_html(br.execution_row(label, status, indent_level, dark=self._dark))

    # ------------------------------------------------------------------
    # Public message API
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> None:
        self._message_log.append(("user", (text,)))
        self._append_html(br.user_bubble(text, dark=self._dark))

    def add_ai_message(
        self,
        text: str,
        thought_prompt: str = "",
        debug_json: str = "",
    ) -> None:
        self._message_log.append(("ai", (text, thought_prompt, debug_json)))
        self._append_html(br.ai_bubble(text, dark=self._dark))
        self._thought_panel.show()
        self._thought_panel.set_text(thought_prompt)
        if debug_json and self._debug_mode:
            self._thought_panel.set_debug_json(debug_json)
        self._current_thought_panel = self._thought_panel

    def add_system_note(self, text: str) -> None:
        self._message_log.append(("system", (text,)))
        compat_label = QLabel(text, self._browser)
        compat_label.hide()
        self._append_html(br.system_note(text, dark=self._dark))

    def show_objectives_card(self, specs: list[dict]) -> None:
        self._message_log.append(("objectives", (specs,)))
        self._append_html(br.objectives_card(specs, dark=self._dark))

    def show_progress_chips(self, specs: list[dict]) -> None:
        self._chips.set_objectives(specs)

    def show_completion(self, status: str, results: dict) -> None:
        elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
        self._message_log.append(("summary", (elapsed, status, results)))
        self._append_html(br.summary_bubble(elapsed, status, results, dark=self._dark))
        self._chips.reset()

    # ------------------------------------------------------------------
    # Streaming thought support
    # ------------------------------------------------------------------

    def on_stream_chunk(self, chunk: str) -> None:
        if self._current_thought_panel:
            self._current_thought_panel.append_chunk(chunk)

    def on_stream_done(self, full_text: str) -> None:
        pass

    def on_stream_error(self, error: str) -> None:
        if self._current_thought_panel and self._debug_mode:
            self._current_thought_panel.set_text(f"[stream error: {error}]")

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def get_state(self) -> ChatState:
        return self._state

    def set_state(self, state: ChatState) -> None:
        prev = self._state
        self._state = state
        if state == ChatState.PLANNING and prev not in (ChatState.PLANNING,):
            self._message_log.append(("state_banner", ("🧠 Planning", "#FF9800")))
            self._rebuild_html()
        elif state == ChatState.EXECUTING and prev != ChatState.EXECUTING:
            self._message_log.append(("state_banner", ("⚙ Executing", "#3F51B5")))
            self._rebuild_html()
        if state == ChatState.EXECUTING:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def start_task(self, task_id: str, specs: list[dict], start_time: float) -> None:
        self._task_id = task_id
        self._start_time = start_time
        self._pending_specs = specs
        self._chips.set_objectives(specs)
        self.set_state(ChatState.EXECUTING)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _on_poll(self) -> None:
        if not self._bridge:
            return
        progress = self._bridge.query_progress()
        if not progress:
            return
        current = progress.get("current_objective", "")
        completed = set(progress.get("completed_objectives", []))
        for spec in self._pending_specs:
            obj_id = spec.get("objective_id", "")
            if obj_id in completed:
                self._chips.mark_passed(obj_id)
            elif obj_id == current:
                self._chips.mark_running(obj_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _render_fragment(self, kind: str, args: tuple) -> str:
        """Re-render a logged message with current dark setting."""
        d = self._dark
        if kind == "user":
            return br.user_bubble(args[0], dark=d)
        if kind == "ai":
            return br.ai_bubble(args[0], dark=d)
        if kind == "system":
            return br.system_note(args[0], dark=d)
        if kind == "objectives":
            return br.objectives_card(args[0], dark=d)
        if kind == "summary":
            return br.summary_bubble(args[0], args[1], args[2], dark=d)
        if kind == "exec_step":
            return br.execution_row(args[0], args[1], args[2], dark=d)
        if kind == "welcome":
            return br.welcome_bubble(dark=d)
        if kind == "state_banner":
            return br.state_banner(args[0], args[1], dark=d)
        return ""

    def _append_html(self, _fragment: str) -> None:
        """Render the full message log into the browser (single source of truth)."""
        self._rebuild_html()

    def _rebuild_html(self) -> None:
        """Re-render entire message log with current theme."""
        fragments = [self._render_fragment(k, a) for k, a in self._message_log]
        bg = "#121212" if self._dark else "#FAFAFA"
        fg = "#E0E0E0" if self._dark else "#212121"
        full_html = (
            f"<html><body style='background:{bg};color:{fg};margin:0;padding:0;'>"
            + "".join(fragments)
            + "</body></html>"
        )
        self._browser.setHtml(full_html)
        QTimer.singleShot(30, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        try:
            import shiboken6
            if not shiboken6.isValid(self._browser):
                return
        except ImportError:
            pass
        sb = self._browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    @property
    def thinking(self) -> ThinkingIndicator:
        return self._thinking

    @property
    def chips(self) -> ObjectiveChipsWidget:
        return self._chips

    @property
    def _msg_container(self) -> QWidget:
        """Backward compat for tests that search findChildren on _msg_container."""
        return self._browser
