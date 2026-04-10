"""Chat panel - spacious task intake and objective review workflow."""
from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    APP_BG,
    ASSISTANT_ACCENT,
    ASSISTANT_SURFACE,
    BORDER,
    DANGER,
    MUTED,
    SUCCESS,
    SURFACE,
    TEXT,
    USER_ACCENT,
    USER_SURFACE,
    WARNING,
    card_qss,
    primary_button_qss,
    secondary_button_qss,
    surface_qss,
)
from ui.widgets import ObjectiveEditorWidget

logger = logging.getLogger(__name__)

_MAX_TASK_DESCRIPTION_LENGTH = 1000
_MIN_COMPOSER_HEIGHT = 120
_MAX_COMPOSER_HEIGHT = 300


def _normalize_text(text: str) -> str:
    normalized = str(text or "")
    replacements = {
        "â†’": "->",
        "→": "->",
        "â€¦": "...",
        "…": "...",
        "â€”": " - ",
        "—": " - ",
        "–": " - ",
        "âœ“": "OK",
        "✓": "OK",
        "âœ—": "X",
        "✗": "X",
        "â–¶": ">",
        "▶": ">",
        "â–¼": "v",
        "▼": "v",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


class ChatState(Enum):
    """Authoritative ChatPanel UI states."""

    IDLE = "idle"
    THINKING = "thinking"
    READY_TO_RUN = "ready_to_run"
    REVIEWING_OBJECTIVES = "reviewing_objectives"
    EXECUTING = "executing"
    STARTUP_BLOCKED = "startup_blocked"


_ALLOWED_TRANSITIONS = {
    (ChatState.IDLE, ChatState.THINKING),
    (ChatState.IDLE, ChatState.EXECUTING),
    (ChatState.THINKING, ChatState.IDLE),
    (ChatState.THINKING, ChatState.READY_TO_RUN),
    (ChatState.THINKING, ChatState.REVIEWING_OBJECTIVES),
    (ChatState.READY_TO_RUN, ChatState.IDLE),
    (ChatState.READY_TO_RUN, ChatState.THINKING),
    (ChatState.READY_TO_RUN, ChatState.EXECUTING),
    (ChatState.REVIEWING_OBJECTIVES, ChatState.IDLE),
    (ChatState.REVIEWING_OBJECTIVES, ChatState.THINKING),
    (ChatState.REVIEWING_OBJECTIVES, ChatState.EXECUTING),
    (ChatState.EXECUTING, ChatState.IDLE),
    (ChatState.STARTUP_BLOCKED, ChatState.IDLE),
}


class _ComposerInput(QTextEdit):
    """Multiline composer that sends on Enter and inserts a newline on Shift+Enter."""

    send_requested = pyqtSignal()

    def text(self) -> str:
        """Compatibility helper mirroring line-edit APIs used in older tests."""
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802
        """Compatibility helper mirroring line-edit APIs used in older code."""
        self.setPlainText(text)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                event.accept()
                self.send_requested.emit()
            return
        super().keyPressEvent(event)


class _MessageCard(QFrame):
    """Full-width transcript card for a user or assistant message."""

    def __init__(self, role: str, text: str, timestamp: str, parent=None) -> None:
        super().__init__(parent)
        is_user = role == "user"
        accent = USER_ACCENT if is_user else ASSISTANT_ACCENT
        surface = USER_SURFACE if is_user else ASSISTANT_SURFACE
        sender = "You" if is_user else "Orchestrator"

        self.setObjectName("MessageCard")
        self.setStyleSheet(card_qss("MessageCard", accent, surface))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QLabel(f"{sender}  |  {timestamp}")
        header.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "font-weight: 700;"
            "letter-spacing: 0.2px;"
            "background: transparent;"
        )
        layout.addWidget(header)

        content = QLabel(_normalize_text(text))
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet(
            f"color: {TEXT};"
            "font-size: 13px;"
            "line-height: 1.45;"
            "background: transparent;"
        )
        layout.addWidget(content)


class _ResultCard(QFrame):
    """Structured result card shown after execution completes."""

    def __init__(self, text: str, summary: dict | None, timestamp: str, parent=None) -> None:
        super().__init__(parent)
        self._result_text = _normalize_text(text)
        self.setObjectName("ResultCard")
        self.setStyleSheet(card_qss("ResultCard", ASSISTANT_ACCENT, ASSISTANT_SURFACE))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        header_lbl = QLabel(f"Orchestrator  |  {timestamp}")
        header_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; font-weight: 700; background: transparent;")
        header_row.addWidget(header_lbl)
        header_row.addStretch(1)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedHeight(22)
        copy_btn.setStyleSheet(
            f"QPushButton {{ color: {MUTED}; background: transparent; border: 1px solid {BORDER};"
            "border-radius: 4px; padding: 0 8px; font-size: 11px; }"
            f"QPushButton:hover {{ color: {TEXT}; border-color: {USER_ACCENT}; }}"
        )
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self._result_text))
        header_row.addWidget(copy_btn)
        root.addLayout(header_row)

        # Answer text
        answer = QPlainTextEdit()
        answer.setReadOnly(True)
        answer.setPlainText(self._result_text)
        answer.setMaximumHeight(180)
        answer.setFrameStyle(QFrame.Shape.NoFrame)
        answer.setStyleSheet(
            f"QPlainTextEdit {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; "
            "border-radius: 8px; padding: 10px 12px; font-size: 13px; }}"
        )
        root.addWidget(answer)

        # Collapsible execution breakdown (only when summary provided)
        if summary and (summary.get("objectives") or summary.get("completed") or summary.get("failed")):
            self._breakdown_visible = False
            self._breakdown_widget = self._build_breakdown(summary)
            self._breakdown_widget.hide()

            toggle_row = QHBoxLayout()
            toggle_row.setContentsMargins(0, 0, 0, 0)
            self._toggle_btn = QPushButton(">  Execution details")
            self._toggle_btn.setStyleSheet(
                f"QPushButton {{ color: {MUTED}; background: transparent; border: none;"
                "font-size: 11px; text-align: left; padding: 0; }"
                f"QPushButton:hover {{ color: {TEXT}; }}"
            )
            self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._toggle_btn.clicked.connect(self._on_toggle)
            toggle_row.addWidget(self._toggle_btn)
            toggle_row.addStretch(1)
            root.addLayout(toggle_row)
            root.addWidget(self._breakdown_widget)

    def _on_toggle(self) -> None:
        self._breakdown_visible = not self._breakdown_visible
        self._breakdown_widget.setVisible(self._breakdown_visible)
        self._toggle_btn.setText("v  Execution details" if self._breakdown_visible else ">  Execution details")

    def _build_breakdown(self, summary: dict) -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(3)

        total = summary.get("total_objectives", 0)
        duration = summary.get("duration_s")
        meta_parts = []
        if total:
            meta_parts.append(f"{total} objective{'s' if total != 1 else ''}")
        if duration is not None:
            meta_parts.append(f"{duration:.1f}s total")
        if meta_parts:
            meta_lbl = QLabel("  ".join(meta_parts))
            meta_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
            layout.addWidget(meta_lbl)

        objective_rows = summary.get("objectives") or []
        if objective_rows:
            for item in objective_rows:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status", "pending")).lower()
                status_text = "OK" if status == "completed" else "FAILED"
                color = SUCCESS if status == "completed" else DANGER
                parts = [f"Obj {item.get('index')}: {_normalize_text(str(item.get('description', '')))[:72]}"]

                duration_s = item.get("duration_s")
                if duration_s is not None:
                    parts.append(f"{float(duration_s):.1f}s")

                attempts = int(item.get("attempt_count", 0) or 0)
                if attempts > 1:
                    noun = "attempt" if attempts == 1 else "attempts"
                    parts.append(f"{attempts} {noun}")

                row = QLabel(f"[{status_text}] " + "  |  ".join(parts))
                row.setWordWrap(True)
                row.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")
                layout.addWidget(row)

                reason = _normalize_text(str(item.get("reason", "") or "").strip())
                if reason:
                    reason_lbl = QLabel(reason[:140])
                    reason_lbl.setWordWrap(True)
                    reason_lbl.setStyleSheet(
                        f"color: {MUTED}; font-size: 11px; background: transparent; padding-left: 14px;"
                    )
                    layout.addWidget(reason_lbl)
        else:
            for idx, desc in summary.get("completed", []):
                row = QLabel(f"[OK] Obj {idx}: {_normalize_text(desc)[:80]}")
                row.setStyleSheet(f"color: {SUCCESS}; font-size: 11px; background: transparent;")
                layout.addWidget(row)

            for idx, desc, reason in summary.get("failed", []):
                row = QLabel(f"[FAILED] Obj {idx}: {_normalize_text(desc)[:60]} - {_normalize_text(str(reason))[:60]}")
                row.setWordWrap(True)
                row.setStyleSheet(f"color: {DANGER}; font-size: 11px; background: transparent;")
                layout.addWidget(row)

        return container


class ChatPanel(QWidget):
    """Spacious work inbox for clarifying a task and approving objectives."""

    message_sent = pyqtSignal(str)
    run_requested = pyqtSignal(str, list)
    cancel_requested = pyqtSignal()
    objective_regenerate_requested = pyqtSignal(str)
    objective_change_requested = pyqtSignal(str, list, str)  # (task, current_objectives, change_request)
    new_task_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._confirmed_task = ""
        self._approved_objectives: list[str] = []
        self._state = ChatState.IDLE
        self._startup_message = ""
        self._startup_blocked = False
        self._status_override: tuple[str, str] | None = None
        self._pending_idle_reenable = False
        self._objective_editor_busy = False
        self._think_dots = 0
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(500)
        self._think_timer.timeout.connect(self._on_think_tick)
        self._setup_ui()
        self._update_composer_metrics()
        self._reconcile_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setObjectName("ChatPanel")
        self.setStyleSheet(f"background-color: {APP_BG};")

        header = QFrame()
        header.setObjectName("ChatHeader")
        header.setStyleSheet(surface_qss("ChatHeader", elevated=True, border_bottom=True))
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_layout.setSpacing(10)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)

        title = QLabel("Task")
        title.setStyleSheet(
            f"color: {TEXT};"
            "font-size: 15px;"
            "font-weight: 700;"
            "background: transparent;"
        )
        title_block.addWidget(title)

        subtitle = QLabel("Describe the task, review the objectives, then run when the plan looks right.")
        subtitle.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "background: transparent;"
        )
        title_block.addWidget(subtitle)
        header_layout.addLayout(title_block)
        header_layout.addStretch(1)

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 12px;"
            "background: transparent;"
        )
        header_layout.addWidget(self.status_label)

        self.new_task_btn = QPushButton("New Task")
        self.new_task_btn.setFixedHeight(28)
        self.new_task_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_task_btn.setStyleSheet(
            f"QPushButton {{ color: {MUTED}; background: transparent; border: 1px solid {BORDER};"
            "border-radius: 6px; padding: 0 10px; font-size: 11px; }"
            f"QPushButton:hover {{ color: {TEXT}; border-color: {USER_ACCENT}; }}"
        )
        self.new_task_btn.setToolTip("Clear the current conversation and start a fresh task")
        self.new_task_btn.clicked.connect(self.new_task_requested.emit)
        self.new_task_btn.setVisible(False)
        header_layout.addWidget(self.new_task_btn)
        root.addWidget(header)

        # Horizontal split: chat column always left, objective sidebar right (hidden until review).
        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.setHandleWidth(4)
        self._content_splitter.setChildrenCollapsible(False)

        left_col = QWidget()
        left_col.setStyleSheet(f"background-color: {APP_BG};")
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {APP_BG}; border: none; }}"
            f"QScrollBar:vertical {{ background: {SURFACE}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {USER_ACCENT}; }}"
        )

        self.messages_widget = QWidget()
        self.messages_widget.setStyleSheet(f"background-color: {APP_BG};")
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(16, 14, 16, 14)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)

        self.scroll.setWidget(self.messages_widget)
        left_layout.addWidget(self.scroll, stretch=1)

        self.composer_frame = QFrame()
        self.composer_frame.setObjectName("ComposerFrame")
        self.composer_frame.setStyleSheet(surface_qss("ComposerFrame", elevated=True, border_top=True))
        composer_layout = QVBoxLayout(self.composer_frame)
        composer_layout.setContentsMargins(16, 14, 16, 14)
        composer_layout.setSpacing(10)

        suggestions = QHBoxLayout()
        suggestions.setContentsMargins(0, 0, 0, 0)
        suggestions.setSpacing(8)
        self._suggestions: list[QPushButton] = []
        for label, seed in (
            ("Inspect a folder", "Review this folder, summarize the files, then propose the safest next action."),
            ("Use a website", "Open a website, gather the requested information, and report back with key findings."),
            ("Drive a desktop app", "Open the target desktop app, complete the requested steps, and confirm the result."),
        ):
            chip = QPushButton(label)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {SURFACE};"
                f"  color: {TEXT};"
                f"  border: 1px solid {BORDER};"
                "  border-radius: 14px;"
                "  padding: 6px 10px;"
                "  font-size: 11px;"
                "}"
                f"QPushButton:hover {{ border-color: {USER_ACCENT}; color: {USER_ACCENT}; }}"
            )
            chip.clicked.connect(lambda _checked=False, value=seed: self.load_task_draft(value))
            suggestions.addWidget(chip)
            self._suggestions.append(chip)
        suggestions.addStretch(1)
        composer_layout.addLayout(suggestions)

        self.input_field = _ComposerInput()
        self.input_field.setObjectName("ComposerInput")
        self.input_field.setPlaceholderText(
            "Describe what to automate, then press Enter to send. Shift+Enter adds a new line."
        )
        self.input_field.setAcceptRichText(False)
        self.input_field.setMinimumHeight(_MIN_COMPOSER_HEIGHT)
        self.input_field.setMaximumHeight(_MAX_COMPOSER_HEIGHT)
        self.input_field.setTabChangesFocus(True)
        self.input_field.setStyleSheet(
            f"QTextEdit {{"
            f"  background-color: {SURFACE};"
            f"  color: {TEXT};"
            f"  border: 1px solid {BORDER};"
            "  border-radius: 10px;"
            "  padding: 10px 12px;"
            "  font-size: 13px;"
            "}"
            f"QTextEdit:focus {{ border-color: {USER_ACCENT}; }}"
            f"QTextEdit:disabled {{ color: {MUTED}; }}"
        )
        self.input_field.send_requested.connect(self._on_send)
        self.input_field.textChanged.connect(self._on_input_text_changed)
        composer_layout.addWidget(self.input_field)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)

        self.hint_label = QLabel("Enter sends. Shift+Enter inserts a line break.")
        self.hint_label.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "background: transparent;"
        )
        footer.addWidget(self.hint_label)

        self.char_count_label = QLabel()
        self.char_count_label.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "background: transparent;"
        )
        footer.addWidget(self.char_count_label)
        footer.addStretch(1)

        self.run_frame = QFrame()
        self.run_frame.setObjectName("RunFrame")
        self.run_frame.setStyleSheet("QFrame#RunFrame { background: transparent; }")
        run_layout = QHBoxLayout(self.run_frame)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(8)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(secondary_button_qss())
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)

        self.run_btn = QPushButton("Execute")
        self.run_btn.setObjectName("RunWorkflowButton")
        self.run_btn.setStyleSheet(primary_button_qss())
        self.run_btn.clicked.connect(self._on_run_clicked)

        run_layout.addWidget(self.cancel_btn)
        run_layout.addWidget(self.run_btn)
        footer.addWidget(self.run_frame)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.setStyleSheet(primary_button_qss(ASSISTANT_ACCENT, "#74c7ba"))
        self.send_btn.clicked.connect(self._on_send)
        footer.addWidget(self.send_btn)

        composer_layout.addLayout(footer)
        left_layout.addWidget(self.composer_frame)
        self._content_splitter.addWidget(left_col)

        self.objective_editor = ObjectiveEditorWidget()
        self.objective_editor.objectives_approved.connect(self._on_objectives_approved)
        self.objective_editor.objectives_cancelled.connect(self._on_objectives_cancelled)
        self.objective_editor.objectives_regenerate_requested.connect(self._on_objective_regenerate_requested)
        self.objective_editor.hide()
        self._content_splitter.addWidget(self.objective_editor)

        root.addWidget(self._content_splitter, stretch=1)

    def add_message(self, role: str, text: str) -> None:
        """Append a transcript item to the inbox."""
        timestamp = datetime.now().strftime("%H:%M")
        card = _MessageCard(role, text, timestamp)
        insert_at = max(0, self.messages_layout.count() - 1)
        self.messages_layout.insertWidget(insert_at, card)
        self._scroll_to_bottom()

    def add_result_card(self, text: str, summary: dict | None = None) -> None:
        """Append a structured result card after execution completes."""
        timestamp = datetime.now().strftime("%H:%M")
        card = _ResultCard(text, summary, timestamp)
        insert_at = max(0, self.messages_layout.count() - 1)
        self.messages_layout.insertWidget(insert_at, card)
        self._scroll_to_bottom()

    def set_run_ready(self, task_summary: str) -> None:
        """Reveal fallback run controls after the clarification flow confirms intent."""
        self._pending_idle_reenable = False
        self._confirmed_task = task_summary
        self._approved_objectives = []
        self._objective_editor_busy = False
        self._status_override = None
        self._set_composer_text(task_summary)
        if self._state == ChatState.STARTUP_BLOCKED:
            self._reconcile_ui()
            return
        self._transition_to(ChatState.READY_TO_RUN)

    def show_objective_editor(self, task_summary: str, objectives: list[str]) -> None:
        """Display the editable objective list for the confirmed task."""
        self._pending_idle_reenable = False
        self._confirmed_task = task_summary
        self._approved_objectives = []
        self._objective_editor_busy = False
        self._status_override = None
        self.objective_editor.set_objectives(task_summary, objectives)
        self.input_field.blockSignals(True)
        self.input_field.clear()
        self.input_field.blockSignals(False)
        self._update_composer_metrics()
        if self._state != ChatState.STARTUP_BLOCKED:
            self._transition_to(ChatState.REVIEWING_OBJECTIVES)
        else:
            self._reconcile_ui()

    def load_task_draft(self, text: str, status_message: str | None = None) -> None:
        """Prefill the composer with reusable task text from history or suggestions."""
        self._confirmed_task = ""
        self._approved_objectives = []
        self._objective_editor_busy = False
        self.input_field.setFocus()
        self.input_field.setPlainText(text)
        cursor = self.input_field.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)
        if status_message:
            self._status_override = (status_message, "muted")
        if self._state not in {ChatState.STARTUP_BLOCKED, ChatState.EXECUTING}:
            self._state = ChatState.IDLE
        self._update_composer_metrics()
        self._reconcile_ui()

    def set_input_enabled(self, enabled: bool) -> None:
        """Compatibility wrapper for the clarification thinking cycle."""
        if not enabled:
            if self._state not in {ChatState.STARTUP_BLOCKED, ChatState.EXECUTING}:
                self._transition_to(ChatState.THINKING)
            return

        if self._state == ChatState.THINKING:
            self._pending_idle_reenable = True
            QTimer.singleShot(0, self._finish_thinking_if_pending)
        else:
            self._reconcile_ui()

    def set_executing(self, is_executing: bool) -> None:
        """Lock or unlock the composer while a task is executing."""
        self._pending_idle_reenable = False
        self._objective_editor_busy = False
        if is_executing:
            if self._state != ChatState.STARTUP_BLOCKED:
                self._transition_to(ChatState.EXECUTING)
            return
        if self._state == ChatState.EXECUTING:
            self._transition_to(ChatState.IDLE)
        else:
            self._reconcile_ui()

    def set_startup_state(self, message: str, block_submission: bool = False) -> None:
        """Mirror startup readiness in the header and lock the composer when needed."""
        self._startup_message = message
        self._startup_blocked = block_submission
        self._pending_idle_reenable = False
        self._objective_editor_busy = False
        if block_submission:
            self._status_override = None
            self._state = ChatState.STARTUP_BLOCKED
            self._reconcile_ui()
            return
        if self._state == ChatState.STARTUP_BLOCKED:
            self._transition_to(ChatState.IDLE)
        else:
            self._reconcile_ui()

    def reset_for_new_session(self) -> None:
        """Clear the inbox for a new task conversation."""
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._confirmed_task = ""
        self._status_override = None
        self._pending_idle_reenable = False
        self._approved_objectives = []
        self._objective_editor_busy = False
        self.input_field.clear()
        self._state = ChatState.STARTUP_BLOCKED if self._startup_blocked else ChatState.IDLE
        self._update_composer_metrics()
        self._reconcile_ui()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        """Keep the composer height in sync with wrapping when the panel width changes."""
        super().resizeEvent(event)
        self._update_composer_metrics()

    def _on_send(self) -> None:
        text = self.input_field.toPlainText().strip()
        if not text:
            return

        if self._state == ChatState.REVIEWING_OBJECTIVES:
            if self._objective_editor_busy:
                return
            current = self.objective_editor.all_objectives()
            self.input_field.clear()
            self._update_composer_metrics()
            self.add_message("user", text)
            self._on_objective_change_requested(current, text)
            return

        if self._state not in {ChatState.IDLE, ChatState.READY_TO_RUN}:
            return
        if len(text) > _MAX_TASK_DESCRIPTION_LENGTH:
            self._confirmed_task = ""
            self._status_override = (
                f"Task text cannot exceed {_MAX_TASK_DESCRIPTION_LENGTH} characters.",
                "warning",
            )
            self._reconcile_ui()
            return
        self._confirmed_task = ""
        self._approved_objectives = []
        self._objective_editor_busy = False
        self._status_override = None
        self.input_field.clear()
        self.add_message("user", text)
        self._transition_to(ChatState.THINKING)
        self.message_sent.emit(text)

    def _on_run_clicked(self) -> None:
        if self._state == ChatState.READY_TO_RUN and self._confirmed_task:
            self._objective_editor_busy = True
            self.run_requested.emit(self._confirmed_task, list(self._approved_objectives))

    def unblock_objective_editor(self) -> None:
        """Un-busy the objective editor after a rejected change request."""
        self._objective_editor_busy = False
        self._status_override = None
        self.objective_editor.set_busy(False)
        self._reconcile_ui()

    def _on_objectives_approved(self, objectives: list[str]) -> None:
        if self._state != ChatState.REVIEWING_OBJECTIVES or not self._confirmed_task:
            return
        self._approved_objectives = list(objectives)
        self._objective_editor_busy = True
        self.run_requested.emit(self._confirmed_task, list(objectives))

    def _on_objectives_cancelled(self) -> None:
        if not self._confirmed_task:
            self._transition_to(ChatState.IDLE)
            return
        self.load_task_draft(
            self._confirmed_task,
            status_message="Objective review cancelled. Edit the task or keep chatting to refine it.",
        )

    def _on_objective_regenerate_requested(self) -> None:
        if self._state != ChatState.REVIEWING_OBJECTIVES or not self._confirmed_task:
            return
        self._objective_editor_busy = True
        self._status_override = ("Refreshing objectives...", "muted")
        self.objective_editor.set_busy(True)
        self._reconcile_ui()
        self.objective_regenerate_requested.emit(self._confirmed_task)

    def _on_objective_change_requested(self, current_objectives: list, change_request: str) -> None:
        if self._state != ChatState.REVIEWING_OBJECTIVES or not self._confirmed_task:
            return
        self._objective_editor_busy = True
        self._status_override = ("Asking AI to update the plan...", "muted")
        self.objective_editor.set_busy(True)
        self._reconcile_ui()
        self.objective_change_requested.emit(self._confirmed_task, current_objectives, change_request)

    def _finish_thinking_if_pending(self) -> None:
        if self._pending_idle_reenable and self._state == ChatState.THINKING:
            self._pending_idle_reenable = False
            self._transition_to(ChatState.IDLE)

    def _transition_to(self, new_state: ChatState) -> bool:
        if self._state == new_state:
            self._reconcile_ui()
            return True
        if new_state == ChatState.STARTUP_BLOCKED:
            self._state = new_state
            self._reconcile_ui()
            return True
        if (self._state, new_state) not in _ALLOWED_TRANSITIONS:
            logger.warning("Invalid ChatPanel transition: %s -> %s", self._state.value, new_state.value)
            self._reconcile_ui()
            return False
        self._state = new_state
        if new_state != ChatState.THINKING:
            self._think_timer.stop()
        if new_state != ChatState.STARTUP_BLOCKED and new_state != ChatState.REVIEWING_OBJECTIVES:
            self._status_override = None
        self._reconcile_ui()
        if new_state == ChatState.THINKING:
            self._think_dots = 0
            self._think_timer.start()
        return True

    def _on_think_tick(self) -> None:
        self._think_dots = (self._think_dots % 3) + 1
        self.status_label.setText("Thinking" + "." * self._think_dots)

    def _reconcile_ui(self) -> None:
        """Single source of truth for all interactive element states."""
        idle_like = self._state in {ChatState.IDLE, ChatState.READY_TO_RUN}
        ready = self._state == ChatState.READY_TO_RUN
        reviewing = self._state == ChatState.REVIEWING_OBJECTIVES
        running = self._state == ChatState.EXECUTING
        interactive = idle_like or reviewing

        self.input_field.setEnabled(interactive and not self._startup_blocked and not running)
        self.send_btn.setEnabled(
            interactive
            and not self._startup_blocked
            and not running
            and not (reviewing and self._objective_editor_busy)
        )
        for chip in self._suggestions:
            chip.setEnabled(idle_like and not self._startup_blocked and not running)

        self.run_frame.setVisible(ready or running)
        self.run_btn.setVisible(ready)
        self.run_btn.setEnabled(ready and bool(self._confirmed_task) and not self._startup_blocked)
        self.cancel_btn.setVisible(running)
        self.cancel_btn.setEnabled(running)
        self.send_btn.setVisible(self._state in {ChatState.IDLE, ChatState.REVIEWING_OBJECTIVES})
        self.send_btn.setText("Request Change" if reviewing else "Send")

        self.objective_editor.set_busy(reviewing and self._objective_editor_busy)
        self.objective_editor.setEnabled(reviewing and not running and not self._startup_blocked)

        # Show "New Task" button whenever there are prior messages and AI is idle.
        has_history = self.messages_layout.count() > 1
        self.new_task_btn.setVisible(
            has_history
            and idle_like
            and not self._startup_blocked
        )

        # Show the objective sidebar when reviewing; hide it otherwise.
        if reviewing and not self.objective_editor.isVisible():
            self.objective_editor.show()
            w = max(400, self._content_splitter.width())
            self._content_splitter.setSizes([int(w * 0.55), int(w * 0.45)])
        elif not reviewing:
            self.objective_editor.hide()

        if self._status_override is not None and self._state != ChatState.EXECUTING:
            text, level = self._status_override
        elif self._state == ChatState.STARTUP_BLOCKED:
            text, level = (self._startup_message or "Startup blocked.", "warning")
        elif self._state == ChatState.THINKING:
            if self._think_timer.isActive():
                return
            text, level = ("Thinking.", "muted")
        elif reviewing and self._objective_editor_busy:
            text, level = ("Refreshing objectives...", "muted")
        elif reviewing:
            text, level = ("Review objectives on the right. Type a change request here and hit \"Request Change\".", "muted")
        elif ready:
            text, level = ("Plan approved. Edit the draft or click Execute.", "muted")
        elif running:
            text, level = ("Execution in progress.", "muted")
        else:
            text, level = ("Enter a task description.", "muted")

        color = WARNING if level == "warning" else MUTED
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color};"
            "font-size: 12px;"
            "background: transparent;"
        )

        if idle_like and not self._startup_blocked:
            self.input_field.setFocus()

    def _update_composer_metrics(self) -> None:
        """Keep the composer readable for longer task descriptions."""
        current_length = len(self.input_field.toPlainText())
        self.char_count_label.setText(f"{current_length}/{_MAX_TASK_DESCRIPTION_LENGTH} characters")
        self.char_count_label.setStyleSheet(
            f"color: {WARNING if current_length > _MAX_TASK_DESCRIPTION_LENGTH else MUTED};"
            "font-size: 11px;"
            "background: transparent;"
        )

        document_height = self.input_field.document().size().height()
        extra_chrome = 24
        new_height = int(document_height + extra_chrome)
        new_height = max(_MIN_COMPOSER_HEIGHT, min(_MAX_COMPOSER_HEIGHT, new_height))
        self.input_field.setFixedHeight(new_height)

    def _on_input_text_changed(self) -> None:
        """Update composer metrics and invalidate approved state when the draft changes."""
        self._update_composer_metrics()
        current_text = self.input_field.toPlainText().strip()
        if self._state == ChatState.READY_TO_RUN and current_text != self._confirmed_task.strip():
            self._confirmed_task = ""
            self._approved_objectives = []
            self._status_override = ("Draft changed. Send it again to regenerate the plan.", "muted")
            self._transition_to(ChatState.IDLE)

    def _set_composer_text(self, text: str) -> None:
        """Sync the hidden composer with the current confirmed task summary."""
        if self.input_field.toPlainText().strip() == text.strip():
            return
        self.input_field.blockSignals(True)
        self.input_field.setPlainText(text)
        cursor = self.input_field.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)
        self.input_field.blockSignals(False)
        self._update_composer_metrics()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()
            ),
        )
