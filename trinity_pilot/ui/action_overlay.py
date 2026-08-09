"""ActionOverlay — transparent, click-through, always-on-top visual cue layer.

Draws a short-lived ripple at the last known action coordinate and a toast
label naming the tool that just ran. Purely local rendering driven by
WorkflowBridge.step_occurred — never minimizes, moves, or focuses any other
window, so it cannot interfere with whatever else is running on the machine.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_RIPPLE_MS = 550
_TOAST_MS = 1400
_ACCENT = QColor("#FF6347")

# Tool names whose args carry screen/window-relative coordinates we can ripple at.
_COORD_TOOLS = {"click_coordinate"}


@dataclass
class _Ripple:
    x: int
    y: int
    radius: float = 6.0
    opacity: float = 0.9


class ActionOverlay(QWidget):
    """Full-screen frameless overlay. Input passes through to whatever is beneath it."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._ripple: _Ripple | None = None
        self._ripple_anim: QPropertyAnimation | None = None
        self._toast_text: str = ""
        self._toast_opacity: float = 0.0
        self._toast_anim: QPropertyAnimation | None = None

        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
        self.setGeometry(geo)

    # ------------------------------------------------------------------
    # Animated properties (driven by QPropertyAnimation)
    # ------------------------------------------------------------------
    def _get_ripple_radius(self) -> float:
        return self._ripple.radius if self._ripple else 0.0

    def _set_ripple_radius(self, value: float) -> None:
        if self._ripple:
            self._ripple.radius = value
            self._ripple.opacity = max(0.0, 1.0 - value / 90.0)
        self.update()

    ripple_radius = Property(float, _get_ripple_radius, _set_ripple_radius)

    def _get_toast_opacity(self) -> float:
        return self._toast_opacity

    def _set_toast_opacity(self, value: float) -> None:
        self._toast_opacity = value
        self.update()

    toast_opacity = Property(float, _get_toast_opacity, _set_toast_opacity)

    # ------------------------------------------------------------------
    # Public API — called from MainWindow's step handler
    # ------------------------------------------------------------------
    def show_action(self, tool_name: str, args: dict) -> None:
        self._toast_text = tool_name
        self._restart_toast_anim()

        if tool_name in _COORD_TOOLS:
            x, y = args.get("x"), args.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                self._ripple = _Ripple(x=int(x), y=int(y))
                self._restart_ripple_anim()
                return
        self._ripple = None
        self.update()

    def _restart_ripple_anim(self) -> None:
        if self._ripple_anim:
            self._ripple_anim.stop()
        anim = QPropertyAnimation(self, b"ripple_radius", self)
        anim.setDuration(_RIPPLE_MS)
        anim.setStartValue(6.0)
        anim.setEndValue(70.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._clear_ripple)
        anim.start()
        self._ripple_anim = anim
        self.show()

    def _clear_ripple(self) -> None:
        self._ripple = None
        self.update()
        self._maybe_hide()

    def _restart_toast_anim(self) -> None:
        if self._toast_anim:
            self._toast_anim.stop()
        anim = QPropertyAnimation(self, b"toast_opacity", self)
        anim.setDuration(_TOAST_MS)
        anim.setKeyValueAt(0.0, 0.0)
        anim.setKeyValueAt(0.15, 1.0)
        anim.setKeyValueAt(0.75, 1.0)
        anim.setKeyValueAt(1.0, 0.0)
        anim.finished.connect(self._maybe_hide)
        anim.start()
        self._toast_anim = anim
        self.show()

    def _maybe_hide(self) -> None:
        ripple_done = self._ripple_anim is None or self._ripple_anim.state() != QPropertyAnimation.State.Running
        toast_done = self._toast_anim is None or self._toast_anim.state() != QPropertyAnimation.State.Running
        if ripple_done and toast_done:
            self.hide()

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._ripple is not None:
            color = QColor(_ACCENT)
            color.setAlphaF(max(0.0, min(1.0, self._ripple.opacity)))
            pen = QPen(color)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = self._ripple.radius
            painter.drawEllipse(
                int(self._ripple.x - r), int(self._ripple.y - r), int(r * 2), int(r * 2)
            )

        if self._toast_opacity > 0.0 and self._toast_text:
            font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
            painter.setFont(font)
            color = QColor(_ACCENT)
            color.setAlphaF(self._toast_opacity)
            painter.setPen(QPen(color))
            metrics = painter.fontMetrics()
            text = self._toast_text
            pad_x, pad_y = 12, 6
            text_w = metrics.horizontalAdvance(text)
            box_w = text_w + pad_x * 2
            box_h = metrics.height() + pad_y * 2
            x = self.width() - box_w - 24
            y = 24
            bg = QColor(20, 20, 20)
            bg.setAlphaF(0.55 * self._toast_opacity)
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, y, box_w, box_h, 8, 8)
            painter.setPen(QPen(color))
            painter.drawText(x + pad_x, y + pad_y + metrics.ascent(), text)
