"""LiveActivityPanel — docked, always-on-top action log for demo visibility.

Locked to the right edge of the primary screen. No free dragging: only a
vertical slide (via the grip) and collapse/expand, so it can never drift
off-screen the way the old glass panel did. Populated purely from
WorkflowBridge.step_occurred (orchestrator Signal objects already flowing
through the app) — no extra AI calls.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from trinity_pilot.orchestrator.signals import (
    BudgetWarning,
    ObjectiveDone,
    ObjectiveFailed,
    ObjectiveStarted,
    StuckSignal,
    WorkerStepSignal,
)

_PANEL_WIDTH = 300
_MAX_LOG_ROWS = 200


def _describe(signal: object) -> tuple[str, str]:
    """Return (label, detail) for a signal, for the log row."""
    if isinstance(signal, WorkerStepSignal):
        return (f"⚙ {signal.tool_name}", f"{signal.objective_id} · step {signal.step_num}")
    if isinstance(signal, ObjectiveStarted):
        return ("▶ objective started", signal.objective_id)
    if isinstance(signal, ObjectiveDone):
        return ("✔ objective done", signal.objective_id)
    if isinstance(signal, ObjectiveFailed):
        return ("✘ objective failed", f"{signal.objective_id}: {signal.failure_reason[:80]}")
    if isinstance(signal, StuckSignal):
        return ("⚠ stuck", f"{signal.objective_id}: {signal.reason}")
    if isinstance(signal, BudgetWarning):
        return ("⏱ budget warning", f"{signal.objective_id}: {signal.budget_type}")
    return (type(signal).__name__, "")


class LiveActivityPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(_PANEL_WIDTH)
        self.setStyleSheet(
            "background:#161B22;color:#E6EDF3;border-left:1px solid #30363D;"
        )

        self._collapsed = False
        self._drag_start_y: int | None = None
        self._drag_start_top: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background:#21262D;border-bottom:1px solid #30363D;")
        header.setCursor(Qt.CursorShape.SizeVerCursor)
        header.mousePressEvent = self._grip_press  # type: ignore[method-assign]
        header.mouseMoveEvent = self._grip_move  # type: ignore[method-assign]
        header.mouseReleaseEvent = self._grip_release  # type: ignore[method-assign]
        hl = QVBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        title_row = QLabel("● Live activity")
        title_row.setStyleSheet("color:#FF6347;font-weight:700;font-size:12px;")
        hl.addWidget(title_row, alignment=Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(header)

        self._collapse_btn = QToolButton()
        self._collapse_btn.setText("–")
        self._collapse_btn.setFixedSize(20, 20)
        self._collapse_btn.setStyleSheet(
            "QToolButton{color:#8B949E;background:transparent;border:none;font-size:14px;}"
        )
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        # place button inside header, top-right
        self._collapse_btn.setParent(header)
        self._collapse_btn.move(_PANEL_WIDTH - 30, 8)

        self._thumb = QLabel()
        self._thumb.setFixedHeight(140)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background:#0D1117;color:#6E7681;font-size:11px;")
        self._thumb.setText("No screenshot yet")
        self._thumb.setScaledContents(False)
        root.addWidget(self._thumb)

        self._current_label = QLabel("Idle")
        self._current_label.setStyleSheet(
            "color:#E6EDF3;font-size:12px;font-weight:600;padding:8px 10px 4px 10px;"
        )
        root.addWidget(self._current_label)

        self._log = QListWidget()
        self._log.setStyleSheet(
            "QListWidget{background:#0D1117;color:#8B949E;border:none;font-size:11px;}"
            "QListWidget::item{padding:4px 10px;border-bottom:1px solid #161B22;}"
        )
        mono = QFont("Consolas", 9)
        self._log.setFont(mono)
        root.addWidget(self._log, stretch=1)

        self._reposition()

    # ------------------------------------------------------------------
    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            return
        height = 60 if self._collapsed else min(420, geo.height() - 40)
        self.setGeometry(geo.right() - _PANEL_WIDTH + 1, geo.top() + 20, _PANEL_WIDTH, height)
        self._thumb.setVisible(not self._collapsed)
        self._log.setVisible(not self._collapsed)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._collapse_btn.setText("+" if self._collapsed else "–")
        self._reposition()

    # Vertical-slide-only drag on the header grip — cannot leave the screen edge.
    def _grip_press(self, event) -> None:
        self._drag_start_y = event.globalPosition().toPoint().y()
        self._drag_start_top = self.y()

    def _grip_move(self, event) -> None:
        if self._drag_start_y is None:
            return
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            return
        dy = event.globalPosition().toPoint().y() - self._drag_start_y
        new_top = max(geo.top(), min(geo.bottom() - self.height(), self._drag_start_top + dy))
        self.move(self.x(), new_top)

    def _grip_release(self, _event) -> None:
        self._drag_start_y = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def append_event(self, signal: object) -> None:
        label, detail = _describe(signal)
        item = QListWidgetItem(f"{label}   {detail}")
        self._log.addItem(item)
        self._log.scrollToBottom()
        while self._log.count() > _MAX_LOG_ROWS:
            self._log.takeItem(0)

        if isinstance(signal, WorkerStepSignal):
            self._current_label.setText(f"{signal.tool_name}  ({signal.objective_id})")
            if signal.thumbnail:
                pix = QPixmap()
                if pix.loadFromData(signal.thumbnail, b"JPG"):
                    scaled = pix.scaled(
                        _PANEL_WIDTH - 16,
                        140,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._thumb.setPixmap(scaled)
        elif isinstance(signal, (ObjectiveStarted, ObjectiveDone, ObjectiveFailed)):
            self._current_label.setText(f"{type(signal).__name__}: {signal.objective_id}")

    def reset(self) -> None:
        self._log.clear()
        self._current_label.setText("Idle")
        self._thumb.setPixmap(QPixmap())
        self._thumb.setText("No screenshot yet")
