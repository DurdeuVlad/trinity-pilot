"""Plan panel — editable objectives list with Run/Cancel buttons."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    BORDER, ERROR, MUTED, PRIMARY, SURFACE, SURFACE_ALT, TEXT, TEXT_STRONG,
    SUCCESS, WARNING,
    primary_button_style, secondary_button_style,
)

_DOMAIN_COLORS = {
    "web": (PRIMARY, "#0a1a2e"),
    "desktop": (SUCCESS, "#0a1f0f"),
    "cli": (WARNING, "#1f1700"),
}


class PlanPanel(QWidget):
    run_clicked = pyqtSignal(list)     # current objectives list
    cancel_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Execution Plan")
        title.setStyleSheet(f"font-size:14px; font-weight:700; color:{TEXT_STRONG};")
        header.addWidget(title)
        header.addStretch()

        self._domain_badge = QLabel("")
        self._domain_badge.setVisible(False)
        self._domain_badge.setStyleSheet(
            f"font-size:11px; font-weight:600; padding:3px 8px; border-radius:10px;"
        )
        header.addWidget(self._domain_badge)
        layout.addLayout(header)

        # Objectives list
        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{"
            f"  background-color: {SURFACE};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 8px;"
            f"  padding: 4px;"
            f"  color: {TEXT};"
            f"  font-size: 13px;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 6px 8px;"
            f"  border-radius: 4px;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background-color: {SURFACE_ALT};"
            f"  color: {TEXT_STRONG};"
            f"}}"
        )
        self._list.setEditTriggers(QListWidget.EditTrigger.DoubleClicked)
        layout.addWidget(self._list, stretch=1)

        hint = QLabel("Double-click an item to edit before running")
        hint.setStyleSheet(f"font-size:11px; color:{MUTED};")
        layout.addWidget(hint)

        # Buttons
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run")
        self._run_btn.setStyleSheet(primary_button_style())
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(secondary_button_style())
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    def show_plan(self, objectives: list[str]) -> None:
        self._list.clear()
        for obj in objectives:
            item = QListWidgetItem(obj)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self._list.addItem(item)
        self._run_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)

    def set_domain(self, domain: str) -> None:
        colors = _DOMAIN_COLORS.get(domain, (MUTED, SURFACE_ALT))
        fg, bg = colors
        self._domain_badge.setText(domain.upper())
        self._domain_badge.setStyleSheet(
            f"font-size:11px; font-weight:600; padding:3px 8px; border-radius:10px;"
            f"color:{fg}; background-color:{bg}; border:1px solid {fg};"
        )
        self._domain_badge.setVisible(True)

    def set_step_active(self, n: int, _text: str) -> None:
        self._highlight_item(n - 1, PRIMARY)

    def set_step_done(self, n: int, success: bool, _output: str) -> None:
        self._highlight_item(n - 1, SUCCESS if success else ERROR)

    def set_executing(self, busy: bool) -> None:
        self._run_btn.setVisible(not busy)
        self._cancel_btn.setVisible(busy)
        self._list.setEnabled(not busy)

    def _highlight_item(self, idx: int, color: str) -> None:
        if 0 <= idx < self._list.count():
            item = self._list.item(idx)
            item.setForeground(QColor(color))

    def _on_run(self) -> None:
        objectives = [
            self._list.item(i).text().strip()
            for i in range(self._list.count())
            if self._list.item(i).text().strip()
        ]
        if objectives:
            self.run_clicked.emit(objectives)
