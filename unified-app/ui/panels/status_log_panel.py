"""AI-style execution log panel - renders progress as a readable thought stream."""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ui.theme import APP_BG, BORDER, MUTED, SUCCESS, SURFACE, TEXT

_AMBER = "#d29922"
_RED = "#f85149"
_BLUE = "#58a6ff"
_GREEN_FAINT = "#0f2a1a"
_RED_FAINT = "#2a0f0f"
_CARD_BG = "#161b22"


def _html_info(msg: str, ts: str) -> str:
    """Regular narration line - what the AI is doing."""
    safe = _esc(msg)
    return (
        f'<div style="padding:2px 10px 2px 10px; color:{TEXT};">'
        f'<span style="color:{MUTED}; font-size:10px;">{ts}&nbsp;&nbsp;</span>'
        f"{safe}</div>"
    )


def _html_thinking(msg: str, ts: str) -> str:
    """Subtle thinking indicator - italic, muted."""
    safe = _esc(msg)
    return (
        f'<div style="padding:2px 10px 2px 14px; color:{MUTED}; font-style:italic;">'
        f"{safe}</div>"
    )


def _html_success(msg: str, ts: str) -> str:
    """Green completion line."""
    safe = _esc(msg)
    return f'<div style="padding:2px 10px; color:{SUCCESS};"><b>[ok]</b>&nbsp;{safe}</div>'


def _html_warning(msg: str, ts: str) -> str:
    """Amber warning - retry, partial result, soft issue."""
    safe = _esc(msg)
    return f'<div style="padding:2px 10px; color:{_AMBER};">[warn]&nbsp;{safe}</div>'


def _html_error(msg: str, ts: str) -> str:
    """Red error - hard failure."""
    safe = _esc(msg)
    return (
        f'<div style="padding:3px 10px; color:{_RED}; '
        f'background:{_RED_FAINT}; border-radius:4px; margin:2px 6px;">'
        f"[x]&nbsp;{safe}</div>"
    )


def _html_step(msg: str, ts: str) -> str:
    """Bold step-header card - new objective starting."""
    if "|" in msg:
        fraction, desc = msg.split("|", 1)
        header = f'<span style="color:{_BLUE}; font-weight:bold;">Step {fraction}</span>'
        body = f'<span style="color:{TEXT}">&nbsp;|&nbsp;{_esc(desc)}</span>'
    else:
        header = f'<span style="color:{_BLUE}; font-weight:bold;">Step</span>'
        body = f'<span style="color:{TEXT}">&nbsp;|&nbsp;{_esc(msg)}</span>'

    return (
        f'<div style="margin:10px 6px 3px 6px; padding:6px 12px; '
        f'background:{_CARD_BG}; border-left:3px solid {_BLUE}; border-radius:0 4px 4px 0;">'
        f"{header}{body}</div>"
    )


def _html_done(msg: str, ts: str) -> str:
    """Final success banner."""
    safe = _esc(msg)
    return (
        f'<div style="margin:12px 6px 4px 6px; padding:8px 12px; '
        f'background:{_GREEN_FAINT}; border-left:3px solid {SUCCESS}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{SUCCESS}; font-weight:bold; font-size:13px;">[done] {safe}</span></div>'
    )


def _html_fail(msg: str, ts: str) -> str:
    """Final failure banner."""
    safe = _esc(msg)
    return (
        f'<div style="margin:12px 6px 4px 6px; padding:8px 12px; '
        f'background:{_RED_FAINT}; border-left:3px solid {_RED}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{_RED}; font-weight:bold; font-size:13px;">[failed] {safe}</span></div>'
    )


def _html_startup(msg: str, ts: str) -> str:
    """Quiet startup line - small and muted."""
    safe = _esc(msg)
    return (
        f'<div style="padding:2px 10px; color:{MUTED}; font-size:10px; font-style:italic;">'
        f"{safe}</div>"
    )


def _esc(text: str) -> str:
    """Minimal HTML escape."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_RENDERERS = {
    "info": _html_info,
    "thinking": _html_thinking,
    "success": _html_success,
    "warning": _html_warning,
    "error": _html_error,
    "step": _html_step,
    "done": _html_done,
    "fail": _html_fail,
    "startup": _html_startup,
}


class StatusLogPanel(QWidget):
    """AI thought-stream execution log - rich HTML, no developer noise."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)
        self.setStyleSheet(f"background-color: {APP_BG};")

        header = QHBoxLayout()
        header.setContentsMargins(10, 0, 10, 6)

        title = QLabel("What I'm doing")
        title.setStyleSheet(
            f"font-size:15px; font-weight:600; color:{TEXT}; padding-left:2px;"
        )
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(24)
        clear_btn.setStyleSheet(
            f"color:{MUTED}; background:transparent; border:1px solid {BORDER}; "
            f"border-radius:4px; padding:0 10px; font-size:11px;"
        )
        clear_btn.clicked.connect(self.clear_log)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.log_text = QTextBrowser()
        self.log_text.setReadOnly(True)
        self.log_text.setOpenLinks(False)
        self.log_text.setStyleSheet(
            f"QTextBrowser {{"
            f"  font-family: 'Segoe UI', Arial, sans-serif;"
            f"  font-size: 13px;"
            f"  background-color: {SURFACE};"
            f"  color: {TEXT};"
            f"  border: none;"
            f"  padding: 4px 0;"
            f"}}"
        )
        layout.addWidget(self.log_text)

    @pyqtSlot(str, str)
    def append_log(self, message: str, level: str = "info") -> None:
        """Append one log entry, rendered as rich HTML."""
        ts = datetime.now().strftime("%H:%M:%S")
        renderer = _RENDERERS.get(level.lower(), _html_info)
        html = renderer(message, ts)
        self.log_text.append(html)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_log(self) -> None:
        """Clear all log content."""
        self.log_text.clear()
