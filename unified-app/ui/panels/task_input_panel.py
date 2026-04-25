"""Task input panel for natural-language orchestration."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


MAX_TASK_DESCRIPTION_LENGTH = 1000


class TaskInputPanel(QWidget):
    """Collect task description and target domain from the user."""

    task_submitted = pyqtSignal(str, str)
    task_cancel_requested = pyqtSignal()
    validation_error = pyqtSignal(str)
    duplicate_submit_ignored = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._submission_in_flight = False
        self._startup_blocked = False
        self._startup_block_reason = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("Task Description")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self.startup_state_label = QLabel("Startup mode: pending.")
        self.startup_state_label.setObjectName("StartupStateLabel")
        self.startup_state_label.setWordWrap(True)
        layout.addWidget(self.startup_state_label)

        self.task_input = QTextEdit()
        self.task_input.setPlaceholderText(
            "Describe what to automate.\n"
            "Examples:\n"
            "- Search Google for AI news and summarize results\n"
            "- Open Notepad, type text, and save\n"
            "- List Python files in current directory"
        )
        self.task_input.setMinimumHeight(60)
        self.task_input.setMaximumHeight(120)
        self.task_input.setObjectName("TaskInput")
        layout.addWidget(self.task_input)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Domain:"))

        self.domain_combo = QComboBox()
        self.domain_combo.addItems(["Auto-detect", "Web", "Desktop", "CLI", "Mixed"])
        self.domain_combo.setObjectName("DomainCombo")
        options_row.addWidget(self.domain_combo)
        options_row.addStretch()

        self.run_btn = QPushButton("Run Task")
        self.run_btn.setObjectName("RunButton")
        self.run_btn.clicked.connect(self.on_run_clicked)
        options_row.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.task_cancel_requested.emit)
        options_row.addWidget(self.cancel_btn)

        layout.addLayout(options_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

    def on_run_clicked(self) -> None:
        """Emit task for orchestration."""
        if self._submission_in_flight:
            self.duplicate_submit_ignored.emit("Task is already running. Duplicate submit ignored.")
            return
        if self._startup_blocked:
            self.validation_error.emit(self._startup_block_reason)
            return
        description = self.task_input.toPlainText().strip()
        if not description:
            self.validation_error.emit("Task description cannot be empty.")
            return
        if len(description) > MAX_TASK_DESCRIPTION_LENGTH:
            self.validation_error.emit(
                f"Task description cannot exceed {MAX_TASK_DESCRIPTION_LENGTH} characters."
            )
            return
        domain_label = self.domain_combo.currentText()
        if domain_label == "Auto-detect":
            domain = self.detect_domain(description)
        else:
            domain = domain_label.lower()
        self._submission_in_flight = True
        self.task_submitted.emit(description, domain)
        self.set_executing(True)

    def detect_domain(self, description: str) -> str:
        """Select execution domain from task text heuristics using shared bridge."""
        from orchestrator.trinity_bridge import TrinityBridge
        return TrinityBridge().suggest_domain(description)

    def set_executing(self, is_executing: bool) -> None:
        """Toggle controls while execution is in progress."""
        if not is_executing:
            self._submission_in_flight = False
        self.run_btn.setEnabled((not is_executing) and not self._startup_blocked)
        self.cancel_btn.setEnabled(is_executing)
        self.task_input.setReadOnly(is_executing)
        self.domain_combo.setEnabled(not is_executing)

    def set_startup_state(self, message: str, block_submission: bool = False) -> None:
        """Update the visible startup mode text and whether task submission is allowed."""

        self._startup_blocked = block_submission
        self._startup_block_reason = message if block_submission else ""
        self.startup_state_label.setText(message)
        self.startup_state_label.setStyleSheet(
            "color: #9a3412;" if block_submission else "color: #166534;"
        )
        self.run_btn.setEnabled((not self._submission_in_flight) and not self._startup_blocked)

    def set_default_domain(self, domain_label: str) -> None:
        """Apply the configured default domain if it matches the available options."""

        index = self.domain_combo.findText(domain_label)
        if index >= 0:
            self.domain_combo.setCurrentIndex(index)
