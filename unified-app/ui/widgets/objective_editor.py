"""Interactive objective editor shown before execution starts."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
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
    primary_button_qss,
    secondary_button_qss,
    surface_qss,
)


class _ObjectiveRow(QFrame):
    """Read-only objective row."""

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

        self.text_field = QLabel(text)
        self.text_field.setWordWrap(True)
        self.text_field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_field.setStyleSheet(
            f"color: {TEXT};"
            f"background-color: {SURFACE_ALT};"
            f"border: 1px solid {BORDER};"
            "border-radius: 8px;"
            "padding: 8px 10px;"
            "font-size: 12px;"
        )
        self.text_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body.addWidget(self.text_field, stretch=1)
        layout.addLayout(body)

    def set_position(self, index: int, total: int) -> None:
        """Refresh user-facing numbering."""
        self.title_label.setText(f"Objective {index}")
        self.position_label.setText(f"{index}/{total}")

    def objective_text(self) -> str:
        """Return the trimmed objective text."""
        return self.text_field.text().strip()


class ObjectiveEditorWidget(QWidget):
    """Objective review panel — users see objectives and approve or request changes via the main composer."""

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

        # ── Bottom actions ─────────────────────────────────────────────
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self.regenerate_button = QPushButton("Regenerate")
        self.regenerate_button.setStyleSheet(secondary_button_qss())
        self.regenerate_button.clicked.connect(lambda _checked=False: self.objectives_regenerate_requested.emit())
        actions.addWidget(self.regenerate_button)

        actions.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(secondary_button_qss())
        self.cancel_button.clicked.connect(lambda _checked=False: self.objectives_cancelled.emit())
        actions.addWidget(self.cancel_button)

        self.approve_button = QPushButton("Approve & Run")
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
        """Lock controls while an LLM call is in flight."""
        self.approve_button.setEnabled(not busy)
        self.regenerate_button.setEnabled(not busy)
        self.regenerate_button.setText("Regenerating..." if busy else "Regenerate")

    def all_objectives(self) -> list[str]:
        """Return all objective texts in current visual order."""
        return [row.objective_text() for row in self._rows if row.objective_text()]

    def _append_row(self, text: str) -> None:
        row = _ObjectiveRow(text, len(self._rows) + 1, len(self._rows) + 1)
        insert_index = max(0, self.rows_layout.count() - 1)
        self.rows_layout.insertWidget(insert_index, row)
        self._rows.append(row)

    def _clear_rows(self) -> None:
        while self._rows:
            row = self._rows.pop()
            self.rows_layout.removeWidget(row)
            row.deleteLater()

    def _refresh_rows(self) -> None:
        total = len(self._rows)
        for index, row in enumerate(self._rows, start=1):
            row.set_position(index, total)

    def _emit_approved_objectives(self) -> None:
        objectives = self.all_objectives()
        if not objectives:
            return
        self.objectives_approved.emit(objectives)
