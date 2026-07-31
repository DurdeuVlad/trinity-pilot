from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QWidget,
)

from trinity_pilot.ui.theme import tok

_CHIP_BASE = (
    "padding:4px 12px;"
    "border-radius:14px;"
    "font-size:11px;"
    "font-weight:600;"
    "margin-right:4px;"
)


def _chip_style(bg: str, fg: str, border: str | None = None) -> str:
    s = _CHIP_BASE + f"background:{bg};color:{fg};"
    if border:
        s += f"border:1px solid {border};"
    else:
        s += "border:none;"
    return s


class ObjectiveChipsWidget(QFrame):
    """Animated chip row showing each objective's execution state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self._pulse_anims: dict[str, QSequentialAnimationGroup] = {}

        self._apply_frame_style()
        self.hide()

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _t(self, name: str) -> str:
        return tok(name, self._dark)

    def _pending(self) -> str:
        return _chip_style(self._t("chip_pending_bg"), self._t("chip_pending_fg"))

    def _running(self) -> str:
        return _chip_style(
            self._t("chip_run_bg"),
            self._t("chip_run_fg"),
            self._t("chip_run_border"),
        )

    def _passed(self) -> str:
        return _chip_style(self._t("chip_done_bg"), self._t("chip_done_fg"))

    def _failed(self) -> str:
        return _chip_style(self._t("chip_fail_bg"), self._t("chip_fail_fg"))

    def _apply_frame_style(self) -> None:
        bg = self._t("surface")
        border = self._t("border")
        self.setStyleSheet(
            f"QFrame{{background:{bg};border:1px solid {border};border-radius:6px;}}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_objectives(self, specs: list[dict]) -> None:
        self._clear_chips()
        for i, spec in enumerate(specs):
            obj_id = spec.get("objective_id", "?")
            label_text = spec.get("goal", spec.get("description", obj_id))
            if len(label_text) > 28:
                label_text = label_text[:25] + "…"
            label = QLabel(label_text)
            label.setToolTip(obj_id)
            label.setStyleSheet(self._pending())
            # Start fully transparent for staggered entrance
            effect = QGraphicsOpacityEffect(label)
            effect.setOpacity(0.0)
            label.setGraphicsEffect(effect)
            self._layout.insertWidget(self._layout.count() - 1, label)
            self._chips[obj_id] = label
            self._chip_labels[obj_id] = label_text
            # Staggered fade-in: 40ms per chip
            QTimer.singleShot(i * 40, lambda lbl=label, eff=effect: self._entrance_fade(lbl, eff))
        self.show()

    def mark_running(self, obj_id: str) -> None:
        chip = self._chips.get(obj_id)
        if not chip:
            return
        chip.setStyleSheet(self._running())
        self._stop_pulse(obj_id)

        effect = QGraphicsOpacityEffect(chip)
        chip.setGraphicsEffect(effect)

        fade_out = QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(600)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.3)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutSine)

        fade_in = QPropertyAnimation(effect, b"opacity")
        fade_in.setDuration(600)
        fade_in.setStartValue(0.3)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutSine)

        group = QSequentialAnimationGroup(chip)
        group.addAnimation(fade_out)
        group.addAnimation(fade_in)
        group.setLoopCount(-1)
        group.start()
        self._pulse_anims[obj_id] = group

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
        self._apply_frame_style()
        # Re-apply pending style to non-running/done chips
        for obj_id, chip in self._chips.items():
            text = chip.text()
            if text.startswith("✓"):
                chip.setStyleSheet(self._passed())
            elif text.startswith("✗"):
                chip.setStyleSheet(self._failed())
            elif obj_id in self._pulse_anims:
                chip.setStyleSheet(self._running())
            else:
                chip.setStyleSheet(self._pending())

    def reset(self) -> None:
        self._clear_chips()
        self.hide()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _entrance_fade(self, label: QLabel, effect: QGraphicsOpacityEffect) -> None:
        try:
            anim = QPropertyAnimation(effect, b"opacity", label)
        except RuntimeError:
            return
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_pulse(self, obj_id: str) -> None:
        group = self._pulse_anims.pop(obj_id, None)
        if group:
            group.stop()
            group.deleteLater()
        chip = self._chips.get(obj_id)
        if chip:
            chip.setGraphicsEffect(None)  # type: ignore[arg-type]  # PySide6 stub omits the None-clears-effect overload
        timer = self._pulse_timers.pop(obj_id, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        self._pulse_state.pop(obj_id, None)

    def _clear_chips(self) -> None:
        for obj_id in list(self._pulse_anims):
            self._stop_pulse(obj_id)
        for obj_id in list(self._pulse_timers):
            self._stop_pulse(obj_id)
        for chip in self._chips.values():
            self._layout.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()
        self._chip_labels.clear()
