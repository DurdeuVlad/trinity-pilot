from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QWidget,
)

_CHIP_BASE = (
    "padding:3px 10px;"
    "border-radius:12px;"
    "font-size:11px;"
    "font-weight:600;"
    "margin-right:4px;"
)
# Light-mode chip styles
_PENDING_STYLE     = _CHIP_BASE + "background:#E0E0E0;color:#616161;"
_RUNNING_STYLE_A   = _CHIP_BASE + "background:#BBDEFB;color:#1565C0;border:2px solid #1565C0;"
_RUNNING_STYLE_B   = _CHIP_BASE + "background:#E3F2FD;color:#1565C0;border:2px solid #1565C0;"
_PASSED_STYLE      = _CHIP_BASE + "background:#C8E6C9;color:#2E7D32;"
_FAILED_STYLE      = _CHIP_BASE + "background:#FFCDD2;color:#C62828;"
# Dark-mode chip styles
_D_PENDING_STYLE   = _CHIP_BASE + "background:#3A3A3A;color:#AAAAAA;"
_D_RUNNING_STYLE_A = _CHIP_BASE + "background:#1A2C3D;color:#64B5F6;border:2px solid #1976D2;"
_D_RUNNING_STYLE_B = _CHIP_BASE + "background:#0D1A26;color:#64B5F6;border:2px solid #1976D2;"
_D_PASSED_STYLE    = _CHIP_BASE + "background:#1A3020;color:#81C784;"
_D_FAILED_STYLE    = _CHIP_BASE + "background:#3D1A1A;color:#EF9A9A;"


class ObjectiveChipsWidget(QGroupBox):
    """Animated chip row showing each objective's execution state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Execution Progress", parent)
        self._dark = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(52)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._container = QWidget()
        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

        self._chips: dict[str, QLabel] = {}
        self._chip_labels: dict[str, str] = {}  # obj_id -> display text
        self._pulse_timers: dict[str, QTimer] = {}
        self._pulse_state: dict[str, bool] = {}

        self.hide()

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _pending(self) -> str:
        return _D_PENDING_STYLE if self._dark else _PENDING_STYLE

    def _running_a(self) -> str:
        return _D_RUNNING_STYLE_A if self._dark else _RUNNING_STYLE_A

    def _running_b(self) -> str:
        return _D_RUNNING_STYLE_B if self._dark else _RUNNING_STYLE_B

    def _passed(self) -> str:
        return _D_PASSED_STYLE if self._dark else _PASSED_STYLE

    def _failed(self) -> str:
        return _D_FAILED_STYLE if self._dark else _FAILED_STYLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_objectives(self, specs: list[dict]) -> None:
        self._clear_chips()
        for spec in specs:
            obj_id = spec.get("objective_id", "?")
            label_text = spec.get("goal", spec.get("description", obj_id))
            if len(label_text) > 28:
                label_text = label_text[:25] + "…"
            label = QLabel(label_text)
            label.setToolTip(obj_id)
            label.setStyleSheet(self._pending())
            self._layout.insertWidget(self._layout.count() - 1, label)
            self._chips[obj_id] = label
            self._chip_labels[obj_id] = label_text
        self.show()

    def mark_running(self, obj_id: str) -> None:
        chip = self._chips.get(obj_id)
        if not chip:
            return
        chip.setStyleSheet(self._running_a())
        self._pulse_state[obj_id] = True
        timer = QTimer(self)
        timer.setInterval(600)
        timer.timeout.connect(lambda oid=obj_id: self._pulse(oid))
        timer.start()
        self._pulse_timers[obj_id] = timer

    def mark_passed(self, obj_id: str) -> None:
        self._stop_pulse(obj_id)
        chip = self._chips.get(obj_id)
        if chip:
            display = self._chip_labels.get(obj_id, obj_id)
            chip.setText("✓ " + display)
            chip.setStyleSheet(self._passed())

    def mark_failed(self, obj_id: str) -> None:
        self._stop_pulse(obj_id)
        chip = self._chips.get(obj_id)
        if chip:
            display = self._chip_labels.get(obj_id, obj_id)
            chip.setText("✗ " + display)
            chip.setStyleSheet(self._failed())

    def apply_dark(self, dark: bool) -> None:
        self._dark = dark
        bg = "#1A1A1A" if dark else "#FFFFFF"
        border = "#2A2A2A" if dark else "#E0E0E0"
        self.setStyleSheet(
            f"QGroupBox{{background:{bg};border:1px solid {border};border-radius:4px;}}"
        )
        # Re-apply pending style to any chips already shown
        for chip in self._chips.values():
            if chip.styleSheet() in (_PENDING_STYLE, _D_PENDING_STYLE):
                chip.setStyleSheet(self._pending())

    def reset(self) -> None:
        self._clear_chips()
        self.hide()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _pulse(self, obj_id: str) -> None:
        chip = self._chips.get(obj_id)
        if not chip:
            return
        state = self._pulse_state.get(obj_id, True)
        chip.setStyleSheet(self._running_a() if state else self._running_b())
        self._pulse_state[obj_id] = not state

    def _stop_pulse(self, obj_id: str) -> None:
        timer = self._pulse_timers.pop(obj_id, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        self._pulse_state.pop(obj_id, None)

    def _clear_chips(self) -> None:
        for obj_id in list(self._pulse_timers):
            self._stop_pulse(obj_id)
        for chip in self._chips.values():
            self._layout.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()
        self._chip_labels.clear()
