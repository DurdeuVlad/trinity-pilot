from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout

from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget


class ObjectiveProgressWidget(QGroupBox):
    """Legacy status bar widget — delegates to ObjectiveChipsWidget internally.

    Kept for backward compatibility. New code should use ObjectiveChipsWidget directly.
    """

    def __init__(self, parent=None) -> None:
        super().__init__("Progress", parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self._chips = ObjectiveChipsWidget(self)
        layout.addWidget(self._chips)

        self._last_obj_id: str = ""

    def update_progress(
        self,
        objective_id: str = "—",
        attempt: int | str = "—",
        domain: str = "—",
    ) -> None:
        if objective_id and objective_id != "—":
            if objective_id != self._last_obj_id:
                self._chips.set_objectives([{"objective_id": objective_id}])
                self._last_obj_id = objective_id
            self._chips.mark_running(objective_id)

    def reset(self) -> None:
        self._last_obj_id = ""
        self._chips.reset()
