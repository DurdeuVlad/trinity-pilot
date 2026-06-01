from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout

_ON  = '<span style="color:#FF6347;font-size:13px;">&#9679;</span>'
_OFF = '<span style="color:#CCCCCC;font-size:13px;">&#9679;</span>'

# 6-frame running-light pattern \u2014 perceived as smooth at 80ms/frame (12.5 fps)
_PATTERNS: list[tuple[bool, bool, bool]] = [
    (True,  False, False),
    (True,  True,  False),
    (False, True,  False),
    (False, True,  True),
    (False, False, True),
    (True,  False, True),
]

_INTERVAL_MS = 80


def _frame_html(pattern: tuple[bool, bool, bool], label: str) -> str:
    dots = "".join(_ON if b else _OFF for b in pattern)
    return (
        f'{dots}&nbsp;&nbsp;'
        f'<span style="color:#FF6347;font-style:italic;font-size:13px;">{label}</span>'
    )


_FRAMES_PLANNING  = [_frame_html(p, "Planning your task")  for p in _PATTERNS]
_FRAMES_EXECUTING = [_frame_html(p, "Running objectives")  for p in _PATTERNS]


class ThinkingIndicator(QWidget):
    """Animated three-dot thinking indicator shown while AI is working."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._frames = _FRAMES_PLANNING
        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setText(self._frames[0])
        layout.addWidget(self._label)
        layout.addStretch()

        self._frame_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

        self.hide()

    def apply_dark(self, dark: bool) -> None:
        pass  # colour is fixed brand orange; no dark variant needed yet

    def set_mode(self, mode: str) -> None:
        """Switch animation text. mode: 'planning' | 'executing'"""
        self._frames = _FRAMES_EXECUTING if mode == "executing" else _FRAMES_PLANNING
        self._frame_idx = 0
        self._label.setText(self._frames[0])

    def start(self) -> None:
        self._frame_idx = 0
        self._label.setText(self._frames[0])
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self._label.setText(self._frames[self._frame_idx])
