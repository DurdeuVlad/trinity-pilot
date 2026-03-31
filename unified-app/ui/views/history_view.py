"""History browser for prior orchestration runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from orchestrator.database import HistoryManager
from orchestrator.database.models import TaskStatus
from ui import theme as ui_theme

_STATUS_OPTIONS = ["All", "pending", "running", "completed", "failed", "cancelled"]
_DEFAULT_DETAIL_MESSAGE = "Select a task to inspect its objectives, steps, and output."
_FILTER_EMPTY_DETAIL_MESSAGE = "No tasks match this filter."
_EMPTY_HISTORY_DETAIL_MESSAGE = "No task history yet. Run a task to see history."
_PLACEHOLDER = "-"


class HistoryView(QWidget):
    """Browse, inspect, import, export, and reuse stored task runs."""

    task_selected = pyqtSignal(str)
    load_into_chat_requested = pyqtSignal(str)
    rerun_requested = pyqtSignal(str)
    export_selected_requested = pyqtSignal(object)
    export_filtered_requested = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history_manager = HistoryManager()
        self._current_task_id: str | None = None
        self._current_tasks: list[Any] = []
        self._setup_ui()
        self.load_history()

    def _setup_ui(self) -> None:
        self.setObjectName("HistoryViewRoot")
        self.setStyleSheet(ui_theme.dark_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Task History")
        title.setStyleSheet(ui_theme.title_style())
        header.addWidget(title)
        header.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setObjectName("HistorySearchInput")
        self.search_input.setPlaceholderText("Search descriptions...")
        self.search_input.setMinimumWidth(240)
        self.search_input.textChanged.connect(self._apply_filters)
        header.addWidget(self.search_input)

        self.status_filter = QComboBox()
        self.status_filter.setObjectName("HistoryStatusFilter")
        self.status_filter.addItems(_STATUS_OPTIONS)
        self.status_filter.currentTextChanged.connect(self._apply_filters)
        header.addWidget(self.status_filter)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("HistoryClearButton")
        self.clear_btn.setVisible(False)
        self.clear_btn.clicked.connect(self.clear_filters)
        header.addWidget(self.clear_btn)

        self.import_btn = QPushButton("Import archive")
        self.import_btn.clicked.connect(self.import_archive)
        header.addWidget(self.import_btn)

        self.export_selected_btn = QPushButton("Export selected")
        self.export_selected_btn.clicked.connect(self.export_selected_archive)
        self.export_selected_btn.setEnabled(False)
        header.addWidget(self.export_selected_btn)

        self.export_filtered_btn = QPushButton("Export filtered")
        self.export_filtered_btn.clicked.connect(self.export_filtered_archive)
        header.addWidget(self.export_filtered_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("HistoryRefreshButton")
        self.refresh_btn.clicked.connect(self.load_history)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.filter_label = QLabel()
        self.filter_label.setObjectName("HistoryFilterLabel")
        self.filter_label.setStyleSheet(ui_theme.muted_style())
        self.filter_label.setVisible(False)
        layout.addWidget(self.filter_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(4)

        table_frame = QFrame()
        table_frame.setObjectName("HistoryListPane")
        table_frame.setStyleSheet(ui_theme.surface_qss("HistoryListPane"))
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)

        self.table = QTableWidget()
        self.table.setObjectName("HistoryTable")
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Created", "Task", "Domain", "Status", "Task ID"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header_view = self.table.horizontalHeader()
        if header_view is not None:
            header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_table_double_click)
        table_layout.addWidget(self.table)
        self.splitter.addWidget(table_frame)

        detail_frame = QFrame()
        detail_frame.setObjectName("HistoryDetailPane")
        detail_frame.setStyleSheet(ui_theme.surface_qss("HistoryDetailPane", elevated=True))
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(12)

        detail_title = QLabel("Run details")
        detail_title.setStyleSheet(ui_theme.section_style(15))
        detail_layout.addWidget(detail_title)

        self.detail_summary = QLabel(_DEFAULT_DETAIL_MESSAGE)
        self.detail_summary.setWordWrap(True)
        self.detail_summary.setStyleSheet(ui_theme.section_style(13))
        detail_layout.addWidget(self.detail_summary)

        meta = QFormLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        self.detail_task_id = QLabel(_PLACEHOLDER)
        self.detail_domain = QLabel(_PLACEHOLDER)
        self.detail_status = QLabel(_PLACEHOLDER)
        self.detail_created = QLabel(_PLACEHOLDER)
        self.detail_started = QLabel(_PLACEHOLDER)
        self.detail_completed = QLabel(_PLACEHOLDER)
        meta.addRow("Task ID", self.detail_task_id)
        meta.addRow("Domain", self.detail_domain)
        meta.addRow("Status", self.detail_status)
        meta.addRow("Created", self.detail_created)
        meta.addRow("Started", self.detail_started)
        meta.addRow("Completed", self.detail_completed)
        detail_layout.addLayout(meta)

        objectives_label = QLabel("Objectives")
        objectives_label.setStyleSheet(ui_theme.section_style())
        detail_layout.addWidget(objectives_label)
        self.plan_steps = QPlainTextEdit()
        self.plan_steps.setReadOnly(True)
        self.plan_steps.setPlaceholderText("Objectives will appear here.")
        self.plan_steps.setMaximumBlockCount(200)
        self.plan_steps.setMinimumHeight(90)
        detail_layout.addWidget(self.plan_steps)

        steps_label = QLabel("Execution steps")
        steps_label.setStyleSheet(ui_theme.section_style())
        detail_layout.addWidget(steps_label)
        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(4)
        self.steps_table.setHorizontalHeaderLabels(["#", "Description", "Status", "Result / Error"])
        self.steps_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.steps_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.steps_table.setAlternatingRowColors(True)
        steps_header = self.steps_table.horizontalHeader()
        if steps_header is not None:
            steps_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            steps_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            steps_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            steps_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.steps_table.setMinimumHeight(160)
        detail_layout.addWidget(self.steps_table)

        payload_label = QLabel("Result payload")
        payload_label.setStyleSheet(ui_theme.section_style())
        detail_layout.addWidget(payload_label)
        self.payload_view = QPlainTextEdit()
        self.payload_view.setReadOnly(True)
        self.payload_view.setPlaceholderText("Final result and error payloads will appear here.")
        self.payload_view.setMinimumHeight(140)
        detail_layout.addWidget(self.payload_view)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.load_into_chat_btn = QPushButton("Load into chat")
        self.load_into_chat_btn.clicked.connect(self._emit_load_into_chat)
        actions.addWidget(self.load_into_chat_btn)

        self.rerun_btn = QPushButton("Rerun")
        self.rerun_btn.clicked.connect(self._emit_rerun)
        actions.addWidget(self.rerun_btn)

        self.detail_export_btn = QPushButton("Export selected")
        self.detail_export_btn.clicked.connect(self.export_selected_archive)
        actions.addWidget(self.detail_export_btn)
        actions.addStretch()
        detail_layout.addLayout(actions)

        self.splitter.addWidget(detail_frame)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 4)
        layout.addWidget(self.splitter, stretch=1)

        self._set_actions_enabled(False)

    def _filtered_tasks(self) -> list[Any]:
        text = self.search_input.text().strip()
        status_text = self.status_filter.currentText()
        status = None if status_text == "All" else TaskStatus(status_text)

        is_filtered = bool(text) or status is not None
        self._update_filter_state(is_filtered, text, status_text)

        if status is not None and text:
            tasks = self.history_manager.get_tasks_by_status(status)
            lowered = text.lower()
            return [
                task
                for task in tasks
                if lowered in task.description.lower() or lowered in task.task_id.lower()
            ]
        if status is not None:
            return self.history_manager.get_tasks_by_status(status)
        if text:
            return self.history_manager.search_tasks(text)
        return self.history_manager.get_recent_tasks()

    def _apply_filters(self) -> None:
        self._render_tasks(self._filtered_tasks())

    def _update_filter_state(self, is_filtered: bool, text: str, status_text: str) -> None:
        self.clear_btn.setVisible(is_filtered)
        self.filter_label.setVisible(is_filtered)
        if not is_filtered:
            return
        parts = []
        if text:
            parts.append(f'search: "{text}"')
        if status_text != "All":
            parts.append(f"status: {status_text}")
        self.filter_label.setText("Filtered by: " + ", ".join(parts))

    def clear_filters(self) -> None:
        """Reset all filters and reload full history."""
        self.search_input.blockSignals(True)
        self.status_filter.blockSignals(True)
        self.search_input.clear()
        self.status_filter.setCurrentIndex(0)
        self.search_input.blockSignals(False)
        self.status_filter.blockSignals(False)
        self.clear_btn.setVisible(False)
        self.filter_label.setVisible(False)
        self.load_history()

    def on_search(self, text: str) -> None:
        """Compatibility helper used by older tests."""
        self.search_input.setText(text)

    def load_history(self) -> None:
        """Reload newest tasks using the active filters."""
        self._render_tasks(self._filtered_tasks())

    def _render_tasks(self, tasks: list[Any]) -> None:
        self._current_tasks = tasks
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            created = task.created_at.strftime("%Y-%m-%d %H:%M:%S") if task.created_at else "-"
            self.table.setItem(row, 0, QTableWidgetItem(created))
            self.table.setItem(row, 1, QTableWidgetItem(task.description))
            self.table.setItem(row, 2, QTableWidgetItem(task.domain))
            self.table.setItem(row, 3, QTableWidgetItem(task.status.value))
            self.table.setItem(row, 4, QTableWidgetItem(task.task_id))

        has_rows = bool(tasks)
        self.export_filtered_btn.setEnabled(has_rows)
        if not has_rows:
            self.table.clearSelection()
            self.table.blockSignals(False)
            self._show_empty_detail(self._empty_detail_message())
            return

        target_task_id = self._current_task_id
        if not any(task.task_id == target_task_id for task in tasks):
            target_task_id = tasks[0].task_id

        self._select_task_row(target_task_id)
        self.table.blockSignals(False)
        self.show_task_details(target_task_id)

    def _select_task_row(self, task_id: str | None) -> None:
        if not task_id:
            self.table.clearSelection()
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 4)
            if item is not None and item.text() == task_id:
                self.table.setCurrentCell(row, 0)
                return
        self.table.clearSelection()

    def _on_selection_changed(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            self._show_empty_detail(self._empty_detail_message())
            return
        row = selected[0].row()
        task_id_item = self.table.item(row, 4)
        if task_id_item is None:
            self._show_empty_detail(self._empty_detail_message())
            return
        self.show_task_details(task_id_item.text(), emit_signal=True)

    def _on_table_double_click(self, row: int, _column: int) -> None:
        task_id_item = self.table.item(row, 4)
        if task_id_item is not None:
            self.show_task_details(task_id_item.text(), emit_signal=True)

    def _show_empty_detail(self, message: str) -> None:
        self._current_task_id = None
        self.detail_summary.setText(message)
        for label in (
            self.detail_task_id,
            self.detail_domain,
            self.detail_status,
            self.detail_created,
            self.detail_started,
            self.detail_completed,
        ):
            label.setText(_PLACEHOLDER)
        self.plan_steps.clear()
        self.steps_table.clearContents()
        self.steps_table.setRowCount(0)
        self.payload_view.clear()
        self._set_actions_enabled(False)

    def _clear_detail_pane(self) -> None:
        self._show_empty_detail(_DEFAULT_DETAIL_MESSAGE)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.export_selected_btn.setEnabled(enabled)
        self.detail_export_btn.setEnabled(enabled)
        self.load_into_chat_btn.setEnabled(enabled)
        self.rerun_btn.setEnabled(enabled)

    def _empty_detail_message(self) -> str:
        if self.search_input.text().strip() or self.status_filter.currentText() != "All":
            return _FILTER_EMPTY_DETAIL_MESSAGE
        return _EMPTY_HISTORY_DETAIL_MESSAGE

    def get_task_details(self, task_id: str) -> dict[str, Any] | None:
        """Return normalized task details for presentation."""
        return self.history_manager.get_task_with_steps(task_id)

    def format_task_details(self, task_id: str) -> str | None:
        """Create user-facing details text for a selected history item."""
        details = self.get_task_details(task_id)
        if details is None:
            return None
        return "\n".join(
            [
                f"Task ID: {details['task_id']}",
                f"Status: {details['status']}",
                f"Domain: {details['domain']}",
                f"Description: {details['description']}",
                f"Created: {details['created_at'] or '-'}",
                f"Started: {details['started_at'] or '-'}",
                f"Completed: {details['completed_at'] or '-'}",
                f"Error: {details.get('error_message') or '-'}",
            ]
        )

    def show_task_details(self, task_id: str, emit_signal: bool = False) -> bool:
        """Populate the detail pane for the given task."""
        details = self.get_task_details(task_id)
        if details is None:
            self._clear_detail_pane()
            return False

        self._current_task_id = task_id
        self.detail_summary.setText(details["description"])
        self.detail_task_id.setText(details["task_id"])
        self.detail_domain.setText(details["domain"])
        self.detail_status.setText(details["status"])
        self.detail_created.setText(details.get("created_at") or "-")
        self.detail_started.setText(details.get("started_at") or "-")
        self.detail_completed.setText(details.get("completed_at") or "-")
        self.plan_steps.setPlainText(self._format_plan_steps(details.get("plan_steps") or []))
        self._render_steps(details.get("steps") or [])
        self.payload_view.setPlainText(self._format_payload(details))
        self._set_actions_enabled(True)

        if emit_signal:
            self.task_selected.emit(task_id)
        return True

    def build_chat_seed(self, task_id: str) -> str | None:
        """Return a compact structured summary suitable for reusing in the chat composer."""
        details = self.get_task_details(task_id)
        if details is None:
            return None
        plan_steps = details.get("plan_steps") or []
        step_lines = [f"- {step['description']} ({step['status']})" for step in (details.get("steps") or [])[:4]]
        summary_lines = [
            "Reuse this prior run as context:",
            f"Goal: {details['description']}",
            f"Domain: {details['domain']}",
            f"Previous status: {details['status']}",
        ]
        if plan_steps:
            summary_lines.append("Objectives:")
            summary_lines.extend(f"- {step}" for step in plan_steps[:6])
        if step_lines:
            summary_lines.append("Recent execution notes:")
            summary_lines.extend(step_lines)
        return "\n".join(summary_lines)

    def export_selected_archive(self) -> None:
        """Export the selected history item to a JSON archive."""
        if self._current_task_id is None:
            return
        self.export_selected_requested.emit([self._current_task_id])
        archive = self.history_manager.export_archive([self._current_task_id])
        self._save_archive_dialog(
            archive,
            default_name=f"{self._current_task_id}.history.json",
        )

    def export_filtered_archive(self) -> None:
        """Export the currently visible history rows to a JSON archive."""
        task_ids = [
            self.table.item(row, 4).text()
            for row in range(self.table.rowCount())
            if self.table.item(row, 4) is not None
        ]
        if not task_ids:
            return
        self.export_filtered_requested.emit(task_ids)
        archive = self.history_manager.export_archive(task_ids)
        self._save_archive_dialog(archive, default_name="history-export.json")

    def import_archive(self) -> None:
        """Import a JSON archive of previous runs."""
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import history archive",
            str(Path.home()),
            "JSON files (*.json)",
        )
        if not file_path:
            return
        try:
            payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
            result = self.history_manager.import_archive(payload)
        except Exception as exc:
            self._show_message_box("Import failed", str(exc), QMessageBox.Icon.Warning)
            return

        imported_ids = result.get("task_ids") or []
        if imported_ids:
            self._current_task_id = imported_ids[0]
        self.load_history()
        if imported_ids:
            self.show_task_details(imported_ids[0])
        self._show_message_box(
            "Import complete",
            f"Imported {result.get('imported_count', 0)} task(s).",
            QMessageBox.Icon.Information,
        )

    def set_history_manager(self, manager: HistoryManager) -> None:
        """Swap backing history manager safely."""
        self.history_manager.close()
        self.history_manager = manager
        self.load_history()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Release DB resources when view is closed."""
        self.history_manager.close()
        super().closeEvent(event)

    def _render_steps(self, steps: list[dict[str, Any]]) -> None:
        self.steps_table.clearContents()
        self.steps_table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            result_summary = self._summarize_step(step)
            self.steps_table.setItem(row, 0, QTableWidgetItem(str(step.get("step_number", row + 1))))
            self.steps_table.setItem(row, 1, QTableWidgetItem(step.get("description") or ""))
            self.steps_table.setItem(row, 2, QTableWidgetItem(step.get("status") or ""))
            self.steps_table.setItem(row, 3, QTableWidgetItem(result_summary))

    def _summarize_step(self, step: dict[str, Any]) -> str:
        if step.get("error_message"):
            return str(step["error_message"])
        result = step.get("result_data") or {}
        if not result:
            return _PLACEHOLDER
        return json.dumps(result, ensure_ascii=True, sort_keys=True)

    def _format_plan_steps(self, steps: list[Any]) -> str:
        if not steps:
            return "No explicit objectives were stored for this run."
        return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))

    def _format_payload(self, details: dict[str, Any]) -> str:
        payload_lines = []
        result_data = details.get("result_data") or {}
        if result_data:
            payload_lines.append("Result data:")
            payload_lines.append(json.dumps(result_data, indent=2, ensure_ascii=True, sort_keys=True))
        error_message = details.get("error_message")
        if error_message:
            if payload_lines:
                payload_lines.append("")
            payload_lines.append("Error:")
            payload_lines.append(str(error_message))
        return "\n".join(payload_lines) if payload_lines else "No final payload was stored for this run."

    def _emit_load_into_chat(self) -> None:
        if self._current_task_id is not None:
            self.load_into_chat_requested.emit(self._current_task_id)

    def _emit_rerun(self) -> None:
        if self._current_task_id is not None:
            self.rerun_requested.emit(self._current_task_id)

    def _show_message_box(self, title: str, text: str, icon: QMessageBox.Icon) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(icon)
        box.setStyleSheet(ui_theme.dark_stylesheet())
        box.exec()

    def _save_archive_dialog(self, archive: dict[str, Any], default_name: str) -> None:
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export history archive",
            str(Path.home() / default_name),
            "JSON files (*.json)",
        )
        if not file_path:
            return
        Path(file_path).write_text(json.dumps(archive, indent=2, ensure_ascii=True), encoding="utf-8")
