from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout


_FRAMES = [
    "\u25cf\u25cb\u25cb  Trinity is thinking",
    "\u25cb\u25cf\u25cb  Trinity is thinking",
    "\u25cb\u25cb\u25cf  Trinity is thinking",
]


class ThinkingIndicator(QWidget):
    """Animated three-dot thinking indicator shown while AI is working."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._label = QLabel(_FRAMES[0])
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

    def start(self) -> None:
        self._frame_idx = 0
        self._label.setText(_FRAMES[0])
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(_FRAMES)
        self._label.setText(_FRAMES[self._frame_idx])
