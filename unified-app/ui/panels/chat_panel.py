"""Chat panel - compact work inbox for task intake and execution control."""
from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    APP_BG,
    ASSISTANT_ACCENT,
    ASSISTANT_SURFACE,
    BORDER,
    MUTED,
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

logger = logging.getLogger(__name__)

_MAX_TASK_DESCRIPTION_LENGTH = 1000


class ChatState(Enum):
    """Authoritative ChatPanel UI states."""

    IDLE = "idle"
    THINKING = "thinking"
    READY_TO_RUN = "ready_to_run"
    EXECUTING = "executing"
    STARTUP_BLOCKED = "startup_blocked"


_ALLOWED_TRANSITIONS = {
    (ChatState.IDLE, ChatState.THINKING),
    (ChatState.IDLE, ChatState.EXECUTING),
    (ChatState.THINKING, ChatState.IDLE),
    (ChatState.THINKING, ChatState.READY_TO_RUN),
    (ChatState.READY_TO_RUN, ChatState.EXECUTING),
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
    """Small transcript card for a user or assistant message."""

    def __init__(self, role: str, text: str, timestamp: str, parent=None) -> None:
        super().__init__(parent)
        is_user = role == "user"
        accent = USER_ACCENT if is_user else ASSISTANT_ACCENT
        sender = "You" if is_user else "Orchestrator"

        self.setObjectName("MessageCard")
        self.setStyleSheet(card_qss("MessageCard", accent, USER_SURFACE if is_user else ASSISTANT_SURFACE))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(0)
        if is_user:
            outer.addStretch(1)

        body = QFrame()
        body.setStyleSheet("background: transparent;")
        body.setMaximumWidth(760)
        body.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)

        header = QLabel(f"{sender}  |  {timestamp}")
        header.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "font-weight: 600;"
            "letter-spacing: 0.2px;"
            "background: transparent;"
        )
        inner.addWidget(header)

        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet(
            f"color: {TEXT};"
            "font-size: 13px;"
            "line-height: 1.35;"
            "background: transparent;"
        )
        inner.addWidget(content)

        outer.addWidget(body)
        if not is_user:
            outer.addStretch(1)


class ChatPanel(QWidget):
    """Compact work inbox for clarifying a task before running it."""

    message_sent = pyqtSignal(str)
    run_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._confirmed_task = ""
        self._state = ChatState.IDLE
        self._startup_message = ""
        self._startup_blocked = False
        self._status_override: tuple[str, str] | None = None
        self._pending_idle_reenable = False
        self._setup_ui()
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
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(10)

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)

        title = QLabel("Task inbox")
        title.setStyleSheet(
            f"color: {TEXT};"
            "font-size: 14px;"
            "font-weight: 700;"
            "background: transparent;"
        )
        title_block.addWidget(title)

        subtitle = QLabel("Use the composer to refine intent, then run when ready.")
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
        root.addWidget(header)

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
        self.messages_layout.setContentsMargins(0, 10, 0, 10)
        self.messages_layout.setSpacing(6)
        self.messages_layout.addStretch(1)

        self.scroll.setWidget(self.messages_widget)
        root.addWidget(self.scroll, stretch=1)

        composer_frame = QFrame()
        composer_frame.setObjectName("ComposerFrame")
        composer_frame.setStyleSheet(surface_qss("ComposerFrame", elevated=True, border_top=True))
        composer_layout = QVBoxLayout(composer_frame)
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
        self.input_field.setMinimumHeight(84)
        self.input_field.setMaximumHeight(110)
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
        footer.addWidget(self.hint_label, stretch=1)

        self.run_frame = QFrame()
        self.run_frame.setObjectName("RunFrame")
        self.run_frame.setStyleSheet("QFrame#RunFrame { background: transparent; }")
        run_layout = QHBoxLayout(self.run_frame)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(8)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(secondary_button_qss())
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)

        self.run_btn = QPushButton("Run workflow")
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
        root.addWidget(composer_frame)

    def add_message(self, role: str, text: str) -> None:
        """Append a transcript item to the inbox."""
        timestamp = datetime.now().strftime("%H:%M")
        card = _MessageCard(role, text, timestamp)
        insert_at = max(0, self.messages_layout.count() - 1)
        self.messages_layout.insertWidget(insert_at, card)
        self._scroll_to_bottom()

    def set_run_ready(self, task_summary: str) -> None:
        """Reveal the run controls after the clarification flow confirms intent."""
        self._pending_idle_reenable = False
        self._confirmed_task = task_summary
        if self._state == ChatState.STARTUP_BLOCKED:
            self._reconcile_ui()
            return
        self._transition_to(ChatState.READY_TO_RUN)

    def load_task_draft(self, text: str, status_message: str | None = None) -> None:
        """Prefill the composer with reusable task text from history or suggestions."""
        self._confirmed_task = ""
        self.input_field.setFocus()
        self.input_field.setPlainText(text)
        cursor = self.input_field.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)
        if status_message:
            self._status_override = (status_message, "muted")
        if self._state != ChatState.STARTUP_BLOCKED and self._state != ChatState.EXECUTING:
            self._state = ChatState.IDLE
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
        self.input_field.clear()
        self._state = ChatState.STARTUP_BLOCKED if self._startup_blocked else ChatState.IDLE
        self._reconcile_ui()

    def _on_send(self) -> None:
        text = self.input_field.toPlainText().strip()
        if not text or self._state != ChatState.IDLE:
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
        self._status_override = None
        self.input_field.clear()
        self.add_message("user", text)
        self._transition_to(ChatState.THINKING)
        self.message_sent.emit(text)

    def _on_run_clicked(self) -> None:
        if self._state == ChatState.READY_TO_RUN and self._confirmed_task:
            self.run_requested.emit(self._confirmed_task)

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
        if new_state != ChatState.STARTUP_BLOCKED:
            self._status_override = None
        self._reconcile_ui()
        return True

    def _reconcile_ui(self) -> None:
        """Single source of truth for all interactive element states."""
        idle = self._state == ChatState.IDLE
        ready = self._state == ChatState.READY_TO_RUN
        running = self._state == ChatState.EXECUTING
        blocked = self._state == ChatState.STARTUP_BLOCKED

        self.input_field.setEnabled(idle)
        self.send_btn.setEnabled(idle)
        for chip in self._suggestions:
            chip.setEnabled(idle)

        self.run_frame.setVisible(ready or running)
        self.run_btn.setEnabled(ready and bool(self._confirmed_task))
        self.cancel_btn.setEnabled(running)

        if self._status_override is not None:
            text, level = self._status_override
        elif self._state == ChatState.STARTUP_BLOCKED:
            text, level = (self._startup_message or "Startup blocked.", "warning")
        elif self._state == ChatState.THINKING:
            text, level = ("Thinking...", "muted")
        elif self._state == ChatState.READY_TO_RUN:
            text, level = ("Ready to run. Click Run Workflow.", "muted")
        elif self._state == ChatState.EXECUTING:
            text, level = ("Running workflow...", "muted")
        else:
            text, level = ("Tell me what you'd like to automate.", "muted")

        color = WARNING if level == "warning" else MUTED
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color};"
            "font-size: 12px;"
            "background: transparent;"
        )

        if idle:
            self.input_field.setFocus()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()
            ),
        )
