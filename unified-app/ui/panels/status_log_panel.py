"""AI-style execution log panel that renders a readable progress stream."""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ui.theme import APP_BG, BORDER, MUTED, SUCCESS, SURFACE, TEXT

_AMBER = "#d29922"
_RED = "#f85149"
_BLUE = "#58a6ff"
_PURPLE = "#bc8cff"
_GREEN_FAINT = "#0f2a1a"
_RED_FAINT = "#2a0f0f"
_PURPLE_FAINT = "#1a1028"
_CARD_BG = "#161b22"


def _normalize_text(text: str) -> str:
    """Normalize unicode and mojibake-heavy strings before rendering."""
    normalized = str(text or "")
    replacements = {
        "â†’": "->",
        "→": "->",
        "â€¦": "...",
        "…": "...",
        "â€”": " - ",
        "—": " - ",
        "–": " - ",
        "Â·": ".",
        "·": ".",
        "âœ“": "OK",
        "✓": "OK",
        "âœ—": "X",
        "✗": "X",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def _html_info(msg: str, ts: str, indent: bool = False) -> str:
    """Regular narration line showing what the orchestrator is doing."""
    safe = _esc(msg)
    pad = "4px 10px 4px 28px" if indent else "4px 10px"
    ts_span = f'<span style="color:{MUTED}; font-size:10px;">{ts}&nbsp;&nbsp;</span>'
    if safe.startswith("-&gt;"):
        content = f'<span style="color:{_BLUE};">-&gt;</span>{safe[5:]}'
    else:
        content = f'<span style="color:#8b949e;">{safe}</span>'
    return f'<div style="padding:{pad}; color:{TEXT};">{ts_span}{content}</div>'


def _html_progress(msg: str, _ts: str) -> str:
    """Muted progress marker between objective sections."""
    safe = _esc(msg)
    return (
        f'<div style="padding:6px 10px 2px 10px; color:{MUTED}; font-size:11px; '
        f'text-transform:uppercase; letter-spacing:0.4px;">{safe}</div>'
    )


def _html_thinking(msg: str, _ts: str, indent: bool = False) -> str:
    """Subtle thinking indicator kept intentionally quiet."""
    safe = _esc(msg)
    pad_left = "32px" if indent else "14px"
    return (
        f'<div style="padding:3px 10px 3px {pad_left}; color:#444d56; font-size:11px;">'
        f'<span style="color:#30363d;">...</span>&nbsp;{safe}</div>'
    )


def _html_success(msg: str, _ts: str, indent: bool = False) -> str:
    """Success line with a compact pill badge."""
    safe = _esc(msg)
    pad = "4px 10px 4px 28px" if indent else "4px 10px"
    badge = (
        f'<span style="background:#1a3a1a; color:{SUCCESS}; padding:1px 7px; '
        f'border-radius:10px; font-size:11px; font-weight:600; margin-right:6px;">ok</span>'
    )
    return f'<div style="padding:{pad};">{badge}<span style="color:{SUCCESS};">{safe}</span></div>'


def _html_warning(msg: str, _ts: str, indent: bool = False) -> str:
    """Warning line with a compact pill badge."""
    safe = _esc(msg)
    pad = "4px 10px 4px 28px" if indent else "4px 10px"
    badge = (
        f'<span style="background:#2a1f00; color:{_AMBER}; padding:1px 7px; '
        f'border-radius:10px; font-size:11px; font-weight:600; margin-right:6px;">warn</span>'
    )
    return f'<div style="padding:{pad};">{badge}<span style="color:{_AMBER};">{safe}</span></div>'


def _html_error(msg: str, _ts: str) -> str:
    """Error line with a stronger card treatment."""
    safe = _esc(msg)
    badge = (
        f'<span style="background:{_RED_FAINT}; color:{_RED}; padding:1px 7px; '
        f'border-radius:10px; font-size:11px; font-weight:600; margin-right:6px;">error</span>'
    )
    return (
        f'<div style="padding:3px 10px; background:{_RED_FAINT}; '
        f'border-radius:4px; margin:2px 6px;">'
        f"{badge}<span style=\"color:{_RED};\">{safe}</span></div>"
    )


def _html_step(msg: str, _ts: str) -> str:
    """Objective header card."""
    if "|" in msg:
        fraction, desc = msg.split("|", 1)
        header = f'<span style="color:{_BLUE}; font-weight:bold;">Objective {fraction}</span>'
        body = f'<span style="color:{TEXT}">&nbsp;|&nbsp;{_esc(desc)}</span>'
    else:
        header = f'<span style="color:{_BLUE}; font-weight:bold;">Objective</span>'
        body = f'<span style="color:{TEXT}">&nbsp;|&nbsp;{_esc(msg)}</span>'

    return (
        f'<div style="margin:10px 6px 3px 6px; padding:6px 12px; '
        f'background:{_CARD_BG}; border-left:3px solid {_BLUE}; border-radius:0 4px 4px 0;">'
        f"{header}{body}</div>"
    )


def _html_done(msg: str, _ts: str) -> str:
    """Final success banner."""
    safe = _esc(msg)
    return (
        f'<div style="margin:12px 6px 4px 6px; padding:8px 12px; '
        f'background:{_GREEN_FAINT}; border-left:3px solid {SUCCESS}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{SUCCESS}; font-weight:bold; font-size:13px;">[done] {safe}</span></div>'
    )


def _html_fail(msg: str, _ts: str) -> str:
    """Final failure banner."""
    safe = _esc(msg)
    return (
        f'<div style="margin:12px 6px 4px 6px; padding:8px 12px; '
        f'background:{_RED_FAINT}; border-left:3px solid {_RED}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{_RED}; font-weight:bold; font-size:13px;">[failed] {safe}</span></div>'
    )


def _html_cancelled(msg: str, _ts: str) -> str:
    """Distinct cancellation banner."""
    safe = _esc(msg)
    return (
        f'<div style="margin:12px 6px 4px 6px; padding:8px 12px; '
        f'background:#1f1a0f; border-left:3px solid {_AMBER}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{_AMBER}; font-weight:bold; font-size:13px;">[cancelled] {safe}</span></div>'
    )


def _html_startup(msg: str, _ts: str) -> str:
    """Quiet startup line."""
    safe = _esc(msg)
    return (
        f'<div style="padding:2px 10px; color:{MUTED}; font-size:10px; font-style:italic;">'
        f"{safe}</div>"
    )


def _html_review(msg: str, _ts: str, indent: bool = False) -> str:
    """Reviewer guidance card."""
    safe = _esc(msg)
    return (
        f'<div style="margin:4px 6px 2px 18px; padding:5px 10px; '
        f'background:{_PURPLE_FAINT}; border-left:3px solid {_PURPLE}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{_PURPLE}; font-weight:bold; font-size:11px;">[review]</span>'
        f'&nbsp;<span style="color:{TEXT}; font-size:12px;">{safe}</span></div>'
    )


def _html_reflect(msg: str, _ts: str, indent: bool = False) -> str:
    """Reflection feedback card."""
    safe = _esc(msg)
    return (
        f'<div style="margin:4px 6px 2px 18px; padding:5px 10px; '
        f'background:#1f1a0f; border-left:3px solid {_AMBER}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{_AMBER}; font-weight:bold; font-size:11px;">[reflect]</span>'
        f'&nbsp;<span style="color:{TEXT}; font-size:12px;">{safe}</span></div>'
    )


def _html_plan(msg: str, _ts: str, indent: bool = False) -> str:
    """Structured live plan update card."""
    safe = _esc(msg).replace("\n", "<br>")
    return (
        f'<div style="margin:4px 6px 2px 18px; padding:6px 10px; '
        f'background:#10253b; border-left:3px solid {_BLUE}; border-radius:0 4px 4px 0;">'
        f'<span style="color:{_BLUE}; font-weight:bold; font-size:11px;">[plan]</span>'
        f'&nbsp;<span style="color:{TEXT}; font-size:12px;">{safe}</span></div>'
    )


def _html_output(msg: str, _ts: str, indent: bool = False) -> str:
    """Monospace command output block."""
    rendered, truncated = _truncate_output(msg)
    lines = _esc(rendered).replace("\n", "<br>")
    margin_left = "22px" if indent else "6px"
    note = (
        f'<div style="margin-top:6px; color:{MUTED}; font-size:10px;">Output truncated in activity log.</div>'
        if truncated else ""
    )
    return (
        f'<div style="margin:4px {margin_left}; padding:6px 10px; background:#0d1117; border-radius:4px; '
        f'font-family:Consolas,monospace; font-size:11px; color:{TEXT}; '
        f'white-space:pre-wrap; word-break:break-all;">'
        f"{lines}{note}</div>"
    )


def _esc(text: str) -> str:
    """Minimal HTML escape."""
    return (
        _normalize_text(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _truncate_output(text: str, max_lines: int = 12, max_chars: int = 900) -> tuple[str, bool]:
    """Keep output blocks readable during long CLI or browser dumps."""
    normalized = str(text or "").rstrip()
    if not normalized:
        return "", False

    lines = normalized.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars].rstrip()
        truncated = True

    if truncated:
        rendered = rendered.rstrip() + "\n..."
    return rendered, truncated


_RENDERERS = {
    "info": _html_info,
    "progress": _html_progress,
    "thinking": _html_thinking,
    "success": _html_success,
    "warning": _html_warning,
    "error": _html_error,
    "step": _html_step,
    "done": _html_done,
    "fail": _html_fail,
    "cancelled": _html_cancelled,
    "startup": _html_startup,
    "output": _html_output,
    "review": _html_review,
    "reflect": _html_reflect,
    "plan": _html_plan,
}

_INDENTED_LEVELS = {"info", "thinking", "success", "warning", "output", "review", "reflect", "plan"}
_SECTION_CLOSING_LEVELS = {"done", "fail", "cancelled"}


class StatusLogPanel(QWidget):
    """Readable activity log for the current run."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._inside_objective = False
        self._last_level = ""
        self._last_error_msg = ""
        self._error_repeat_count = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)
        self.setStyleSheet(f"background-color: {APP_BG};")

        header = QHBoxLayout()
        header.setContentsMargins(10, 0, 10, 6)

        title = QLabel("Activity")
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
        """Append one log entry rendered as rich HTML."""
        ts = datetime.now().strftime("%H:%M:%S")
        lvl = level.lower()

        if lvl == "thinking" and self._last_level == "thinking":
            return

        # Collapse repeated identical errors so the log doesn't flood.
        if lvl == "error":
            if message == self._last_error_msg:
                self._error_repeat_count += 1
                # Every 3 repeats emit a single collapsed notice instead of more error cards.
                if self._error_repeat_count % 3 == 0:
                    indent = self._inside_objective
                    html = _html_warning(
                        f"Still failing \u00d7{self._error_repeat_count} \u2014 still retrying\u2026",
                        ts,
                        indent=indent,
                    )
                    self.log_text.append(html)
                    scrollbar = self.log_text.verticalScrollBar()
                    scrollbar.setValue(scrollbar.maximum())
                return
            self._last_error_msg = message
            self._error_repeat_count = 1
        elif lvl not in ("thinking",):
            self._last_error_msg = ""
            self._error_repeat_count = 0

        if lvl == "info" and message.startswith("Executing objective "):
            self._inside_objective = False
            lvl = "progress"
        elif lvl == "step":
            self._inside_objective = True
        elif lvl in _SECTION_CLOSING_LEVELS:
            self._inside_objective = False

        self._last_level = lvl

        renderer = _RENDERERS.get(lvl, _html_info)
        indent = self._inside_objective and lvl in _INDENTED_LEVELS

        if lvl in _INDENTED_LEVELS:
            html = renderer(message, ts, indent=indent)
        else:
            html = renderer(message, ts)

        self.log_text.append(html)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self) -> None:
        """Clear all log content."""
        self._inside_objective = False
        self._last_level = ""
        self._last_error_msg = ""
        self._error_repeat_count = 0
        self.log_text.clear()

    def append_cli_step(self, obj_index: int, step: dict) -> None:
        """Append a completed CLI step as a structured command card."""
        action = _esc(step.get("action", ""))
        command = _esc(step.get("command", ""))
        summary = _esc(step.get("stdout_summary", ""))
        status = step.get("status", "success")
        verification = step.get("verification")
        next_action = step.get("next_action")
        step_index = step.get("step_index", 0)
        total = step.get("total", 0)

        if status == "success":
            badge_bg = "#1a3a1a"
            badge_color = SUCCESS
            badge_text = "OK"
            action_color = TEXT
        else:
            badge_bg = _RED_FAINT
            badge_color = _RED
            badge_text = "X"
            action_color = _RED

        counter = f"{step_index + 1}/{total}" if total else str(step_index + 1)

        badge = (
            f'<span style="background:{badge_bg}; color:{badge_color}; padding:1px 6px; '
            f'border-radius:10px; font-size:10px; font-weight:600; margin-right:6px;">{badge_text}</span>'
        )
        counter_span = (
            f'<span style="float:right; color:{MUTED}; font-size:10px;">{counter}</span>'
        )

        verify_badge = ""
        if verification == "passed":
            verify_badge = (
                f'&nbsp;<span style="color:{SUCCESS}; font-size:10px; font-weight:600;">[VERIFIED]</span>'
            )
        elif verification == "failed":
            verify_badge = (
                f'&nbsp;<span style="color:{_RED}; font-size:10px; font-weight:600;">[VERIFY X]</span>'
            )

        next_line = ""
        if next_action:
            next_line = (
                f'<div style="color:{MUTED}; font-size:10px; font-style:italic; '
                f'margin-top:2px;">-> Next: {_esc(next_action)}</div>'
            )

        html = (
            f'<div style="margin:3px 6px; padding:5px 10px; background:{_CARD_BG}; '
            f'border-left:3px solid {"#1a3a1a" if status == "success" else _RED_FAINT}; '
            f'border-radius:0 4px 4px 0;">'
            f'{counter_span}'
            f'<div>{badge}<span style="color:{action_color}; font-size:12px;">{action}</span></div>'
            f'<div style="color:#555d6b; font-family:Consolas,monospace; font-size:10px; '
            f'margin-top:2px;">$ {command}</div>'
        )
        if summary:
            html += (
                f'<div style="color:#8b949e; font-size:11px; margin-top:2px;">'
                f'{summary}{verify_badge}</div>'
            )
        elif verify_badge:
            html += f'<div style="font-size:11px; margin-top:2px;">{verify_badge}</div>'
        html += next_line + '</div>'

        self.log_text.append(html)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
