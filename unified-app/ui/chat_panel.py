"""Chat panel — task input and message history."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    ASSISTANT_ACCENT, ASSISTANT_SURFACE, BORDER, ERROR, PRIMARY,
    SURFACE, SURFACE_ALT, TEXT, USER_ACCENT, USER_SURFACE,
    primary_button_style,
)


class _InputBox(QPlainTextEdit):
    """Multi-line input that submits on Enter (Shift+Enter = newline)."""

    submitted = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self.submitted.emit()
        else:
            super().keyPressEvent(event)


def _bubble(role: str, text: str) -> str:
    if role == "user":
        bg, border, name_color = USER_SURFACE, USER_ACCENT, USER_ACCENT
        name = "You"
    else:
        bg, border, name_color = ASSISTANT_SURFACE, ASSISTANT_ACCENT, ASSISTANT_ACCENT
        name = "Assistant"
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    return (
        f'<div style="margin:6px 4px; padding:10px 12px; border-radius:10px;'
        f'background:{bg}; border-left:3px solid {border};">'
        f'<div style="font-size:11px; font-weight:700; color:{name_color}; margin-bottom:4px;">{name}</div>'
        f'<div style="font-size:13px; color:{TEXT};">{safe}</div>'
        f"</div>"
    )


class ChatPanel(QWidget):
    task_submitted = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Message history
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setStyleSheet(
            f"QTextEdit {{"
            f"  background-color: {SURFACE};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 8px;"
            f"  padding: 8px;"
            f"}}"
        )
        layout.addWidget(self._history, stretch=1)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._input = _InputBox()
        self._input.setPlaceholderText("Describe what you want to automate… (Enter to send)")
        self._input.setMaximumHeight(80)
        self._input.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: {SURFACE_ALT};"
            f"  color: {TEXT};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 8px;"
            f"  padding: 8px;"
            f"  font-size: 13px;"
            f"}}"
            f"QPlainTextEdit:focus {{ border-color: {PRIMARY}; }}"
        )
        self._input.submitted.connect(self._on_send)
        input_row.addWidget(self._input)

        self._send_btn = QPushButton("Send")
        self._send_btn.setStyleSheet(primary_button_style())
        self._send_btn.setFixedWidth(72)
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._send_btn, alignment=Qt.AlignmentFlag.AlignBottom)

        layout.addLayout(input_row)

    def show_message(self, text: str, role: str = "assistant") -> None:
        self._history.insertHtml(_bubble(role, text))
        self._history.insertPlainText("\n")
        sb = self._history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def show_result(self, success: bool, output: str) -> None:
        level = "success" if success else "error"
        prefix = "Done:" if success else "Failed:"
        color = PRIMARY if success else ERROR
        safe_out = output.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = (
            f'<div style="margin:6px 4px; padding:10px 12px; border-radius:10px;'
            f'background:{SURFACE_ALT}; border-left:3px solid {color};">'
            f'<div style="font-size:11px; font-weight:700; color:{color}; margin-bottom:4px;">{prefix}</div>'
            f'<div style="font-size:13px; color:{TEXT}; font-family:monospace; white-space:pre-wrap;">{safe_out}</div>'
            f"</div>"
        )
        self._history.insertHtml(html)
        self._history.insertPlainText("\n")
        sb = self._history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_busy(self, busy: bool) -> None:
        self._input.setEnabled(not busy)
        self._send_btn.setEnabled(not busy)
        if busy:
            self._send_btn.setText("…")
        else:
            self._send_btn.setText("Send")

    def _on_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self.show_message(text, role="user")
        self._input.clear()
        self.task_submitted.emit(text)
