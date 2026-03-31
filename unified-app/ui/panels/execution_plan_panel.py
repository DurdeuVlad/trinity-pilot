"""Execution plan panel with per-step status visualization."""
from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui.theme import (
    APP_BG,
    BORDER,
    DANGER,
    SUCCESS,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_WEAK,
)


class StepWidget(QFrame):
    """Widget representing one step in the execution plan."""

    STATUS_STYLES = {
        "pending": {
            "badge": "P",
            "surface": SURFACE,
            "text": TEXT,
            "accent": BORDER,
        },
        "running": {
            "badge": "R",
            "surface": "#15283d",
            "text": TEXT,
            "accent": "#2f80ed",
        },
        "completed": {
            "badge": "OK",
            "surface": "#10251a",
            "text": "#d7f7de",
            "accent": SUCCESS,
        },
        "failed": {
            "badge": "X",
            "surface": "#2b1518",
            "text": "#ffe0e0",
            "accent": DANGER,
        },
    }

    def __init__(self, step_number: int, description: str, parent=None) -> None:
        super().__init__(parent)
        self.step_number = step_number
        self.description = description
        self.status = "pending"
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.status_label = QLabel("P")
        self.status_label.setFixedWidth(24)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.text_label = QLabel(f"Objective {self.step_number}: {self.description}")
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label, stretch=1)
        self._update_appearance()

    def set_status(self, status: str) -> None:
        self.status = status
        self._update_appearance()

    def _update_appearance(self) -> None:
        style = self.STATUS_STYLES.get(self.status, self.STATUS_STYLES["failed"])
        self.status_label.setText(style["badge"])
        self.setStyleSheet(
            "QFrame {"
            f"background-color: {style['surface']};"
            f"color: {style['text']};"
            f"border: 1px solid {style['accent']};"
            f"border-left: 4px solid {style['accent']};"
            "border-radius: 8px;"
            "}"
            "QLabel {"
            f"color: {style['text']};"
            "background: transparent;"
            "border: none;"
            "}"
        )


class ExecutionPlanPanel(QWidget):
    """Displays generated plan steps and their execution state."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.step_widgets: List[StepWidget] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background-color: {APP_BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("Execution Objectives and Steps")
        title.setStyleSheet(
            f"font-size: 16px;"
            f"font-weight: 700;"
            f"color: {TEXT};"
        )
        layout.addWidget(title)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {APP_BG}; border: none; }}"
            f"QScrollBar:vertical {{ background: {SURFACE}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}"
        )

        self.steps_container = QWidget()
        self.steps_container.setStyleSheet(f"background-color: {APP_BG};")
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setSpacing(6)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.addStretch()
        self.scroll_area.setWidget(self.steps_container)
        layout.addWidget(self.scroll_area)

        self.empty_label = QLabel("No objectives yet. Submit a task to generate objectives.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {TEXT_WEAK};"
            f"font-style: italic;"
            f"padding: 20px 12px;"
            f"background-color: {SURFACE_ALT};"
            f"border: 1px dashed {BORDER};"
            f"border-radius: 10px;"
        )
        self.steps_layout.insertWidget(0, self.empty_label)

    @pyqtSlot(list)
    def display_plan(self, steps: List[str]) -> None:
        """Render a new plan."""
        self.clear_plan()
        self.empty_label.hide()
        for index, step in enumerate(steps, start=1):
            widget = StepWidget(index, step)
            self.step_widgets.append(widget)
            self.steps_layout.insertWidget(index - 1, widget)

    @pyqtSlot(int, str)
    def update_step_status(self, step_number: int, status: str) -> None:
        """Set status for one step by one-based index."""
        if 0 < step_number <= len(self.step_widgets):
            self.step_widgets[step_number - 1].set_status(status)

    def clear_plan(self) -> None:
        """Remove all currently displayed steps."""
        for widget in self.step_widgets:
            widget.deleteLater()
        self.step_widgets.clear()
        self.empty_label.show()
