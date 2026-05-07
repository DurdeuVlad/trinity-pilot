from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel


class ObjectiveProgressWidget(QGroupBox):
    """Status bar widget showing current objective execution state."""

    def __init__(self, parent=None) -> None:
        super().__init__("Progress", parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._obj_label = QLabel("Objective: —")
        self._attempt_label = QLabel("Attempt: —")
        self._domain_label = QLabel("Domain: —")

        for lbl in (self._obj_label, self._attempt_label, self._domain_label):
            layout.addWidget(lbl)
        layout.addStretch()

    def update_progress(
        self,
        objective_id: str = "—",
        attempt: int | str = "—",
        domain: str = "—",
    ) -> None:
        self._obj_label.setText(f"Objective: {objective_id}")
        self._attempt_label.setText(f"Attempt: {attempt}")
        self._domain_label.setText(f"Domain: {domain}")

    def reset(self) -> None:
        self.update_progress()
