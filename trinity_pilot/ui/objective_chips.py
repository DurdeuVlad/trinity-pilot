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
_PENDING_STYLE = _CHIP_BASE + "background:#E0E0E0;color:#616161;"
_RUNNING_STYLE_A = _CHIP_BASE + "background:#BBDEFB;color:#1565C0;border:2px solid #1565C0;"
_RUNNING_STYLE_B = _CHIP_BASE + "background:#E3F2FD;color:#1565C0;border:2px solid #1565C0;"
_PASSED_STYLE = _CHIP_BASE + "background:#C8E6C9;color:#2E7D32;"
_FAILED_STYLE = _CHIP_BASE + "background:#FFCDD2;color:#C62828;"


class ObjectiveChipsWidget(QGroupBox):
    """Animated chip row showing each objective's execution state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Execution Progress", parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(44)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._container = QWidget()
        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

        self._chips: dict[str, QLabel] = {}
        self._pulse_timers: dict[str, QTimer] = {}
        self._pulse_state: dict[str, bool] = {}

        self.hide()

    def set_objectives(self, specs: list[dict]) -> None:
        self._clear_chips()
        for spec in specs:
            obj_id = spec.get("objective_id", "?")
            label = QLabel(obj_id)
            label.setStyleSheet(_PENDING_STYLE)
            self._layout.insertWidget(self._layout.count() - 1, label)
            self._chips[obj_id] = label
        self.show()

    def mark_running(self, obj_id: str) -> None:
        chip = self._chips.get(obj_id)
        if not chip:
            return
        chip.setStyleSheet(_RUNNING_STYLE_A)
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
            chip.setText(f"\u2713 {obj_id}")
            chip.setStyleSheet(_PASSED_STYLE)

    def mark_failed(self, obj_id: str) -> None:
        self._stop_pulse(obj_id)
        chip = self._chips.get(obj_id)
        if chip:
            chip.setText(f"\u2717 {obj_id}")
            chip.setStyleSheet(_FAILED_STYLE)

    def reset(self) -> None:
        self._clear_chips()
        self.hide()

    def _pulse(self, obj_id: str) -> None:
        chip = self._chips.get(obj_id)
        if not chip:
            return
        state = self._pulse_state.get(obj_id, True)
        chip.setStyleSheet(_RUNNING_STYLE_A if state else _RUNNING_STYLE_B)
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
