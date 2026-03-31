"""Full-screen AI control HUD shown during desktop-takeover executions."""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.theme import (
        BORDER,
        ERROR,
        PRIMARY,
        SURFACE_ALT,
        SUCCESS,
        TEXT,
        TEXT_STRONG,
        TEXT_WEAK,
    )
except ImportError:
    BORDER = "#30363d"
    ERROR = "#f85149"
    PRIMARY = "#58a6ff"
    SURFACE_ALT = "#1f2630"
    SUCCESS = "#3fb950"
    TEXT = "#cdd9e5"
    TEXT_STRONG = "#f0f6fc"
    TEXT_WEAK = "#8b949e"

_PANEL_W = 420
_PANEL_MAX_STEPS_VISIBLE = 7
_STEP_ROW_H = 28
_MARGIN = 18
_GLASS_ALPHA = 85

_DOMAIN_LABEL: dict[str, str] = {
    "browser": "Browser agent",
    "desktop": "Desktop agent",
    "cli": "CLI agent",
    "mixed": "Multi-domain agent",
}

_STATUS_ICON: dict[str, str] = {
    "pending": ".",
    "running": ">",
    "completed": "OK",
    "failed": "X",
}
_STATUS_COLOR: dict[str, str] = {
    "pending": TEXT_WEAK,
    "running": PRIMARY,
    "completed": SUCCESS,
    "failed": ERROR,
}
_PULSE_CHARS = (">", ":")


class _GlassPaneOverlay(QWidget):
    """Full-screen semi-transparent dim that stays click-through on Windows."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowOpacity(0.0)
        self._anim: Optional[QPropertyAnimation] = None
        self.hide()

    def show_glass(self) -> None:
        if not _supports_overlay_windows():
            self.hide()
            return
        screen = _target_screen()
        if screen is None:
            return
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self._make_click_through()
        self._fade(0.0, 1.0, 320)

    def hide_glass(self, on_done=None) -> None:
        if not _supports_overlay_windows():
            self.hide()
            if on_done:
                on_done()
            return

        def _finish() -> None:
            self.hide()
            if on_done:
                on_done()

        self._fade(self.windowOpacity(), 0.0, 220, on_done=_finish)

    def _make_click_through(self) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00000020 | 0x00080000)
        except Exception:
            pass

    def _fade(self, from_v: float, to_v: float, ms: int, on_done=None) -> None:
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(ms)
        self._anim.setStartValue(from_v)
        self._anim.setEndValue(to_v)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_done:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, _GLASS_ALPHA))
        painter.end()


class _StepRow(QWidget):
    """One row in the HUD step list."""

    def __init__(self, description: str) -> None:
        super().__init__()
        self.setFixedHeight(_STEP_ROW_H)
        self._status = "pending"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._icon = QLabel(_STATUS_ICON["pending"])
        self._icon.setFixedWidth(18)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)

        self._text = QLabel(description)
        self._text.setWordWrap(False)
        self._text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._text)
        self._apply_style()

    def set_running(self) -> None:
        self._status = "running"
        self._apply_style()

    def set_completed(self) -> None:
        self._status = "completed"
        self._icon.setText(_STATUS_ICON["completed"])
        self._apply_style()

    def set_failed(self) -> None:
        self._status = "failed"
        self._icon.setText(_STATUS_ICON["failed"])
        self._apply_style()

    def pulse(self, frame: int) -> None:
        if self._status == "running":
            self._icon.setText(_PULSE_CHARS[frame % len(_PULSE_CHARS)])

    def _apply_style(self) -> None:
        color = _STATUS_COLOR.get(self._status, TEXT_WEAK)
        icon_weight = "600" if self._status == "running" else "500"
        self._icon.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: {icon_weight}; background: transparent;"
        )
        if self._status == "running":
            self._text.setStyleSheet(
                f"color: {TEXT_STRONG}; font-size: 12px; font-weight: 600; background: transparent;"
            )
        elif self._status == "failed":
            self._text.setStyleSheet(
                f"color: {ERROR}; font-size: 12px; background: transparent;"
            )
        else:
            self._text.setStyleSheet(
                f"color: {TEXT_WEAK}; font-size: 12px; background: transparent;"
            )


class ExecutionOverlay(QWidget):
    """Interactive HUD panel shown while the AI controls the desktop."""

    stop_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_PANEL_W)
        self.setWindowOpacity(0.0)

        self._glass = _GlassPaneOverlay()
        self._step_rows: list[_StepRow] = []
        self._running_idx: Optional[int] = None
        self._pulse_frame = 0
        self._anim: Optional[QPropertyAnimation] = None
        self._task_text = "Preparing..."
        self._steps_scroll: Optional[QScrollArea] = None

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(550)
        self._pulse_timer.timeout.connect(self._on_pulse)

        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("HUDCard")
        card.setStyleSheet(
            f"QFrame#HUDCard {{ background-color: rgba(13, 17, 23, 235); border: 1px solid {BORDER}; border-radius: 12px; }}"
        )
        root.addWidget(card)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self._pulse_dot = QLabel("o")
        self._pulse_dot.setStyleSheet(f"color: {PRIMARY}; font-size: 10px; background: transparent;")
        header_row.addWidget(self._pulse_dot)

        self._header_label = QLabel("AI IN CONTROL")
        self._header_label.setStyleSheet(
            f"color: {TEXT_STRONG}; font-size: 12px; font-weight: 700; letter-spacing: 1px; background: transparent;"
        )
        header_row.addWidget(self._header_label)
        header_row.addStretch()

        self._domain_chip = QLabel("...")
        self._domain_chip.setStyleSheet(
            f"color: {TEXT_WEAK}; font-size: 11px; background: transparent;"
        )
        header_row.addWidget(self._domain_chip)
        inner.addLayout(header_row)
        inner.addWidget(self._divider())

        self._task_label = QLabel(self._task_text)
        self._task_label.setWordWrap(True)
        self._task_label.setStyleSheet(f"color: {TEXT}; font-size: 12px; background: transparent;")
        inner.addWidget(self._task_label)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self._progress_label = QLabel("Step 0 of 0")
        self._progress_label.setStyleSheet(
            f"color: {TEXT_WEAK}; font-size: 11px; background: transparent;"
        )
        progress_row.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background-color: {SURFACE_ALT}; border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background-color: {PRIMARY}; border-radius: 2px; }}"
        )
        progress_row.addWidget(self._progress_bar, stretch=1)
        inner.addLayout(progress_row)
        inner.addWidget(self._divider())

        self._steps_container = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_container)
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(0)

        self._empty_label = QLabel("Waiting for plan...")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {TEXT_WEAK}; font-size: 11px; font-style: italic; background: transparent;"
        )
        self._steps_layout.addWidget(self._empty_label)

        self._steps_scroll = QScrollArea()
        self._steps_scroll.setWidget(self._steps_container)
        self._steps_scroll.setWidgetResizable(True)
        self._steps_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._steps_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._steps_scroll.setFixedHeight(_STEP_ROW_H * _PANEL_MAX_STEPS_VISIBLE + 4)
        self._steps_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        inner.addWidget(self._steps_scroll)
        inner.addWidget(self._divider())

        self._narration_label = QLabel("")
        self._narration_label.setWordWrap(True)
        self._narration_label.setFixedHeight(36)
        self._narration_label.setStyleSheet(
            f"color: {TEXT_WEAK}; font-size: 11px; font-style: italic; background: transparent;"
        )
        inner.addWidget(self._narration_label)
        inner.addWidget(self._divider())

        stop_row = QHBoxLayout()
        stop_row.setSpacing(12)

        self._stop_btn = QPushButton("STOP AI")
        self._stop_btn.setFixedHeight(36)
        self._stop_btn.setStyleSheet(
            f"QPushButton {{ background-color: {ERROR}; color: #ffffff; border: none; border-radius: 8px; font-size: 12px; font-weight: 700; }}"
            "QPushButton:hover { background-color: #ff7b72; }"
            "QPushButton:pressed { background-color: #da3633; }"
        )
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        stop_row.addWidget(self._stop_btn, stretch=1)

        hint = QLabel("Ctrl+Alt+End")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hint.setStyleSheet(f"color: {TEXT_WEAK}; font-size: 10px; background: transparent;")
        stop_row.addWidget(hint)
        inner.addLayout(stop_row)

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
        line.setFixedHeight(1)
        return line

    def show_for_domain(self, domain: str) -> None:
        """Animate both the glass pane and this panel into view."""
        self._domain_chip.setText(_DOMAIN_LABEL.get(domain, domain.capitalize() + " agent"))
        self._task_label.setText(self._task_text)
        self._narration_label.setText("")
        self._clear_steps()
        if not _supports_overlay_windows():
            return
        self._glass.show_glass()
        self._reposition()
        self.show()
        self.raise_()
        self._fade(0.0, 1.0, 320)
        self._pulse_timer.start()

    def hide_overlay(self) -> None:
        """Fade out both windows."""
        self._pulse_timer.stop()
        if not _supports_overlay_windows():
            self.hide()
            self._glass.hide()
            return
        self._glass.hide_glass()
        self._fade(self.windowOpacity(), 0.0, 220, on_done=self.hide)

    def update_step(self, idx: int, description: str) -> None:
        """Backward-compatible single-step update entrypoint."""
        self.set_step_started(idx, description)

    def set_task(self, task_description: str) -> None:
        """Show the task the AI is working on."""
        max_chars = 90
        self._task_text = (
            task_description
            if len(task_description) <= max_chars
            else task_description[: max_chars - 3] + "..."
        )
        self._task_label.setText(self._task_text)

    def set_plan(self, steps: list[str]) -> None:
        """Populate the step list when the plan is generated."""
        self._clear_steps()
        if not steps:
            return
        self._empty_label.setVisible(False)
        self._progress_bar.setRange(0, len(steps))
        self._progress_bar.setValue(0)
        self._progress_label.setText(f"Step 0 of {len(steps)}")
        for description in steps:
            row = _StepRow(description)
            self._step_rows.append(row)
            self._steps_layout.addWidget(row)

    def set_step_started(self, idx: int, description: str) -> None:
        """Mark step ``idx`` (1-based) as running."""
        self._running_idx = idx
        row = self._get_row(idx)
        if row is not None:
            row.set_running()
            QTimer.singleShot(50, lambda: self._scroll_to_row(idx))
        self._progress_label.setText(f"Step {idx} of {len(self._step_rows)}")

    def set_step_completed(self, idx: int) -> None:
        """Mark step ``idx`` (1-based) as completed and advance progress."""
        row = self._get_row(idx)
        if row is not None:
            row.set_completed()
        completed = sum(1 for step in self._step_rows if step._status == "completed")  # noqa: SLF001
        self._progress_bar.setValue(completed)

    def set_step_failed(self, idx: int) -> None:
        """Mark step ``idx`` (1-based) as failed."""
        row = self._get_row(idx)
        if row is not None:
            row.set_failed()

    def set_narration(self, text: str, level: str = "info") -> None:
        """Show the latest AI status message beneath the step list."""
        if level in ("thinking", "info", "step", "warning", "error", "success"):
            trimmed = text[:120] + ("..." if len(text) > 120 else "")
            self._narration_label.setText(trimmed)

    def _clear_steps(self) -> None:
        for row in self._step_rows:
            row.setParent(None)  # type: ignore[call-overload]
        self._step_rows.clear()
        self._running_idx = None
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Step 0 of 0")
        self._empty_label.setVisible(True)

    def _get_row(self, idx: int) -> Optional[_StepRow]:
        position = idx - 1
        if 0 <= position < len(self._step_rows):
            return self._step_rows[position]
        return None

    def _scroll_to_row(self, idx: int) -> None:
        row = self._get_row(idx)
        if row is None or self._steps_scroll is None:
            return
        self._steps_scroll.ensureWidgetVisible(row, 0, _STEP_ROW_H)

    def _reposition(self) -> None:
        screen = _target_screen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.adjustSize()
        height = self.sizeHint().height()
        self.move(geometry.right() - _PANEL_W - _MARGIN, geometry.bottom() - height - _MARGIN)

    def _fade(self, from_v: float, to_v: float, ms: int, on_done=None) -> None:
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(ms)
        self._anim.setStartValue(from_v)
        self._anim.setEndValue(to_v)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_done:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def _on_pulse(self) -> None:
        self._pulse_frame += 1
        if self._running_idx is not None:
            row = self._get_row(self._running_idx)
            if row is not None:
                row.pulse(self._pulse_frame)
        if self._pulse_frame % 2 == 0:
            self._pulse_dot.setStyleSheet(
                f"color: {PRIMARY}; font-size: 10px; background: transparent;"
            )
        else:
            self._pulse_dot.setStyleSheet(
                f"color: {BORDER}; font-size: 10px; background: transparent;"
            )


def _target_screen():
    """Choose the most relevant screen for the takeover HUD."""
    screen = QApplication.screenAt(QCursor.pos())
    if screen is not None:
        return screen
    active_window = QApplication.activeWindow()
    if active_window is not None and active_window.windowHandle() is not None:
        window_screen = active_window.windowHandle().screen()
        if window_screen is not None:
            return window_screen
    return QApplication.primaryScreen()


def _supports_overlay_windows() -> bool:
    """Return whether the current Qt platform can safely show takeover HUD windows."""
    app = QApplication.instance()
    if app is None:
        return False
    return app.platformName().lower() not in {"offscreen", "minimal", "minimalegl"}
