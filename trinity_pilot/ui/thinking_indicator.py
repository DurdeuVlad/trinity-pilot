from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout


_FRAMES_PLANNING = [
    "\u25cf\u25cb\u25cb  Planning your task",
    "\u25cb\u25cf\u25cb  Planning your task",
    "\u25cb\u25cb\u25cf  Planning your task",
]

_FRAMES_EXECUTING = [
    "\u25cf\u25cb\u25cb  Running objectives",
    "\u25cb\u25cf\u25cb  Running objectives",
    "\u25cb\u25cb\u25cf  Running objectives",
]


class ThinkingIndicator(QWidget):
    """Animated three-dot thinking indicator shown while AI is working."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._frames = _FRAMES_PLANNING
        self._label = QLabel(self._frames[0])
        self._label.setStyleSheet(
            "color:#FF6347; font-style:italic; font-size:13px;"
        )
        layout.addWidget(self._label)
        layout.addStretch()

        self._frame_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(400)
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
