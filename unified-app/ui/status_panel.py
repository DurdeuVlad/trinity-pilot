"""Status panel — scrolling HTML execution log."""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from ui.theme import (
    BORDER, ERROR, MUTED, PRIMARY, SUCCESS, SURFACE, TEXT, WARNING,
)

_COLORS = {
    "info": MUTED,
    "step": PRIMARY,
    "success": SUCCESS,
    "error": ERROR,
    "warning": WARNING,
}

_LEVEL_ICONS = {
    "info": "·",
    "step": "▶",
    "success": "✓",
    "error": "✗",
    "warning": "!",
}


def _row(text: str, level: str) -> str:
    color = _COLORS.get(level, MUTED)
    icon = _LEVEL_ICONS.get(level, "·")
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<div style="margin:2px 0; color:{color}; font-size:12px; font-family:monospace;">'
        f'<span style="opacity:0.5;">{icon}</span>&nbsp;{safe}</div>'
    )


class StatusPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scroll_pending = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"QTextEdit {{"
            f"  background-color: {SURFACE};"
            f"  color: {TEXT};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 8px;"
            f"  padding: 8px;"
            f"  font-family: 'Consolas', 'Courier New', monospace;"
            f"  font-size: 12px;"
            f"}}"
        )
        layout.addWidget(self._log)

    def append(self, text: str, level: str = "info") -> None:
        self._log.insertHtml(_row(text, level))
        self._log.insertPlainText("\n")
        self._schedule_scroll()

    def clear(self) -> None:
        self._log.clear()

    def _schedule_scroll(self) -> None:
        if not self._scroll_pending:
            self._scroll_pending = True
            QTimer.singleShot(50, self._do_scroll)

    def _do_scroll(self) -> None:
        self._scroll_pending = False
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
