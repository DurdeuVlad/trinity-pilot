"""Interactive objective editor shown before execution starts."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    APP_BG,
    BORDER,
    MUTED,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    USER_ACCENT,
    WARNING,
    primary_button_qss,
    secondary_button_qss,
    surface_qss,
)


class _ObjectiveRow(QFrame):
    """Editable objective row with selection and reorder controls."""

    changed = pyqtSignal()
    delete_requested = pyqtSignal()
    move_up_requested = pyqtSignal()
    move_down_requested = pyqtSignal()

    def __init__(self, text: str, index: int, total: int, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui(text, index, total)

    def _setup_ui(self, text: str, index: int, total: int) -> None:
        self.setObjectName("ObjectiveRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setStyleSheet(
            "QFrame#ObjectiveRow {"
            f"background-color: {SURFACE};"
            f"border: 1px solid {BORDER};"
            "border-radius: 10px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.enabled_checkbox = QCheckBox()
        self.enabled_checkbox.setChecked(True)
        self.enabled_checkbox.stateChanged.connect(lambda _state: self.changed.emit())
        header.addWidget(self.enabled_checkbox, alignment=Qt.AlignmentFlag.AlignTop)

        self.title_label = QLabel(f"Objective {index}")
        self.title_label.setStyleSheet(
            f"color: {TEXT};"
            "font-size: 12px;"
            "font-weight: 700;"
            "background: transparent;"
        )
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.position_label = QLabel(f"{index}/{total}")
        self.position_label.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "background: transparent;"
        )
        header.addWidget(self.position_label)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        self.text_field = QLineEdit(text)
        self.text_field.setPlaceholderText("Describe the objective")
        self.text_field.textChanged.connect(lambda _text: self.changed.emit())
        self.text_field.setStyleSheet(
            f"QLineEdit {{"
            f"background-color: {SURFACE_ALT};"
            f"color: {TEXT};"
            f"border: 1px solid {BORDER};"
            "border-radius: 8px;"
            "padding: 8px 10px;"
            "font-size: 12px;"
            "}"
            f"QLineEdit:focus {{ border-color: {USER_ACCENT}; }}"
        )
        body.addWidget(self.text_field, stretch=1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setStyleSheet(secondary_button_qss())
        self.edit_button.clicked.connect(lambda _checked=False: self.text_field.setFocus())
        actions.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setStyleSheet(secondary_button_qss())
        self.delete_button.clicked.connect(lambda _checked=False: self.delete_requested.emit())
        actions.addWidget(self.delete_button)

        self.up_button = QPushButton("Up")
        self.up_button.setStyleSheet(secondary_button_qss())
        self.up_button.clicked.connect(lambda _checked=False: self.move_up_requested.emit())
        actions.addWidget(self.up_button)

        self.down_button = QPushButton("Down")
        self.down_button.setStyleSheet(secondary_button_qss())
        self.down_button.clicked.connect(lambda _checked=False: self.move_down_requested.emit())
        actions.addWidget(self.down_button)

        body.addLayout(actions)
        layout.addLayout(body)

    def set_position(self, index: int, total: int) -> None:
        """Refresh user-facing numbering and button state."""
        self.title_label.setText(f"Objective {index}")
        self.position_label.setText(f"{index}/{total}")
        self.up_button.setEnabled(index > 1)
        self.down_button.setEnabled(index < total)

    def objective_text(self) -> str:
        """Return the trimmed objective text."""
        return self.text_field.text().strip()

    def is_selected(self) -> bool:
        """Return whether this objective should be included when approved."""
        return self.enabled_checkbox.isChecked()


class ObjectiveEditorWidget(QWidget):
    """Interactive editor for reviewing and approving execution objectives."""

    objectives_approved = pyqtSignal(list)
    objectives_cancelled = pyqtSignal()
    objectives_regenerate_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[_ObjectiveRow] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("ObjectiveEditorHeader")
        header.setStyleSheet(surface_qss("ObjectiveEditorHeader", elevated=True))
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(4)

        title = QLabel("Review execution objectives")
        title.setStyleSheet(
            f"color: {TEXT};"
            "font-size: 14px;"
            "font-weight: 700;"
            "background: transparent;"
        )
        header_layout.addWidget(title)

        self.summary_label = QLabel("Adjust the plan before execution starts.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "background: transparent;"
        )
        header_layout.addWidget(self.summary_label)

        self.selection_label = QLabel("0 selected")
        self.selection_label.setStyleSheet(
            f"color: {MUTED};"
            "font-size: 11px;"
            "font-weight: 600;"
            "background: transparent;"
        )
        header_layout.addWidget(self.selection_label)
        layout.addWidget(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {APP_BG}; border: none; }}"
            f"QScrollBar:vertical {{ background: {SURFACE}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}"
        )
        self.scroll_area.setMinimumHeight(180)

        self.rows_widget = QWidget()
        self.rows_widget.setStyleSheet(f"background-color: {APP_BG};")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll_area.setWidget(self.rows_widget)
        layout.addWidget(self.scroll_area, stretch=1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self.add_button = QPushButton("Add objective")
        self.add_button.setStyleSheet(secondary_button_qss())
        self.add_button.clicked.connect(self._on_add_clicked)
        actions.addWidget(self.add_button)

        self.regenerate_button = QPushButton("Regenerate")
        self.regenerate_button.setStyleSheet(secondary_button_qss())
        self.regenerate_button.clicked.connect(lambda _checked=False: self.objectives_regenerate_requested.emit())
        actions.addWidget(self.regenerate_button)

        actions.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(secondary_button_qss())
        self.cancel_button.clicked.connect(lambda _checked=False: self.objectives_cancelled.emit())
        actions.addWidget(self.cancel_button)

        self.approve_button = QPushButton("Use objectives")
        self.approve_button.setStyleSheet(primary_button_qss())
        self.approve_button.clicked.connect(self._emit_approved_objectives)
        actions.addWidget(self.approve_button)

        layout.addLayout(actions)

    def set_objectives(self, task_summary: str, objectives: list[str]) -> None:
        """Display a fresh objective list for the provided task summary."""
        self.summary_label.setText(task_summary)
        self._clear_rows()
        for objective in objectives or [task_summary]:
            self._append_row(objective)
        self._refresh_rows()

    def set_busy(self, busy: bool) -> None:
        """Lock editing actions while the plan is being regenerated."""
        for row in self._rows:
            row.setEnabled(not busy)
        self.add_button.setEnabled(not busy)
        self.approve_button.setEnabled(not busy and self._has_selected_objectives())
        self.regenerate_button.setEnabled(not busy)
        self.regenerate_button.setText("Regenerating..." if busy else "Regenerate")

    def selected_objectives(self) -> list[str]:
        """Return the approved subset in current visual order."""
        return [
            row.objective_text()
            for row in self._rows
            if row.is_selected() and row.objective_text()
        ]

    def _append_row(self, text: str) -> None:
        row = _ObjectiveRow(text, len(self._rows) + 1, len(self._rows) + 1)
        row.changed.connect(self._refresh_rows)
        row.delete_requested.connect(lambda row=row: self._delete_row(row))
        row.move_up_requested.connect(lambda row=row: self._move_row(row, -1))
        row.move_down_requested.connect(lambda row=row: self._move_row(row, 1))
        insert_index = max(0, self.rows_layout.count() - 1)
        self.rows_layout.insertWidget(insert_index, row)
        self._rows.append(row)

    def _clear_rows(self) -> None:
        while self._rows:
            row = self._rows.pop()
            self.rows_layout.removeWidget(row)
            row.deleteLater()

    def _delete_row(self, row: _ObjectiveRow) -> None:
        if row not in self._rows:
            return
        self._rows.remove(row)
        row.deleteLater()
        if not self._rows:
            self._append_row("")
        self._refresh_rows()

    def _move_row(self, row: _ObjectiveRow, direction: int) -> None:
        if row not in self._rows:
            return
        index = self._rows.index(row)
        target = index + direction
        if target < 0 or target >= len(self._rows):
            return
        self._rows[index], self._rows[target] = self._rows[target], self._rows[index]
        self._rebuild_row_order()
        self._refresh_rows()

    def _rebuild_row_order(self) -> None:
        for row in self._rows:
            self.rows_layout.removeWidget(row)
        for index, row in enumerate(self._rows):
            self.rows_layout.insertWidget(index, row)

    def _refresh_rows(self) -> None:
        total = len(self._rows)
        for index, row in enumerate(self._rows, start=1):
            row.set_position(index, total)

        selected_count = len(self.selected_objectives())
        total_count = len([row for row in self._rows if row.objective_text()])
        self.selection_label.setText(f"{selected_count} selected of {total_count}")
        self.selection_label.setStyleSheet(
            f"color: {WARNING if selected_count == 0 else MUTED};"
            "font-size: 11px;"
            "font-weight: 600;"
            "background: transparent;"
        )
        self.approve_button.setEnabled(selected_count > 0)

    def _has_selected_objectives(self) -> bool:
        return bool(self.selected_objectives())

    def _on_add_clicked(self) -> None:
        self._append_row("")
        self._refresh_rows()
        self._rows[-1].text_field.setFocus()

    def _emit_approved_objectives(self) -> None:
        approved = self.selected_objectives()
        if not approved:
            self._refresh_rows()
            return
        self.objectives_approved.emit(approved)
