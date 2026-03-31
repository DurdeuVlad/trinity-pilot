"""Tests for history view rendering."""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from orchestrator.database.models import TaskStatus
from ui import theme as ui_theme
from ui.views.history_view import HistoryView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_history_view_loads_rows(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_history_manager(view.history_manager.__class__(str(tmp_path / "history.db")))
    view.history_manager.create_task("row_1", "Task one", "cli")
    view.load_history()
    assert view.table.rowCount() == 1


def test_history_view_exposes_stable_object_names(app, qtbot) -> None:
    view = HistoryView()
    qtbot.addWidget(view)
    assert view.search_input.objectName() == "HistorySearchInput"
    assert view.table.objectName() == "HistoryTable"
    assert view.refresh_btn.objectName() == "HistoryRefreshButton"
    assert view.status_filter.objectName() == "HistoryStatusFilter"
    assert view.clear_btn.objectName() == "HistoryClearButton"
    assert view.filter_label.objectName() == "HistoryFilterLabel"


def test_history_view_applies_dark_theme(app, qtbot) -> None:
    view = HistoryView()
    qtbot.addWidget(view)
    assert ui_theme.BG in view.styleSheet()
    assert "QTableWidget" in view.styleSheet()


def test_history_view_formats_task_details(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_history_manager(view.history_manager.__class__(str(tmp_path / "history.db")))
    view.history_manager.create_task("row_42", "Open notepad", "desktop", ["Open app"])
    view.history_manager.add_step("row_42", 1, "Launch app")
    view.history_manager.update_step_status("row_42", 1, TaskStatus.COMPLETED, result_data={"launched": True})
    view.history_manager.complete_task("row_42", result_data={"launched": True})

    details = view.format_task_details("row_42")

    assert details is not None
    assert "Task ID: row_42" in details
    assert "Status: completed" in details
    assert "Domain: desktop" in details
    assert "Description: Open notepad" in details


def test_history_view_updates_detail_pane_on_selection(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_history_manager(view.history_manager.__class__(str(tmp_path / "history.db")))
    view.history_manager.create_task("row_detail", "Inspect details", "desktop", ["First objective"])
    view.history_manager.add_step("row_detail", 1, "Launch app")

    assert view.show_task_details("row_detail")

    assert view.detail_summary.text() == "Inspect details"
    assert view.detail_task_id.text() == "row_detail"
    assert "First objective" in view.plan_steps.toPlainText()
    assert view.steps_table.rowCount() == 1
    assert view.load_into_chat_btn.isEnabled()


def test_history_view_builds_chat_seed(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_history_manager(view.history_manager.__class__(str(tmp_path / "history.db")))
    view.history_manager.create_task("row_seed", "Open calculator", "desktop", ["Launch calculator"])
    view.history_manager.add_step("row_seed", 1, "Launch calculator")

    seed = view.build_chat_seed("row_seed")

    assert seed is not None
    assert "Reuse this prior run as context:" in seed
    assert "Open calculator" in seed
    assert "desktop" in seed


def test_history_view_emits_action_signals(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_history_manager(view.history_manager.__class__(str(tmp_path / "history.db")))
    view.history_manager.create_task("row_action", "Action task", "cli")
    view.show_task_details("row_action")

    loaded: list[str] = []
    rerun: list[str] = []
    view.load_into_chat_requested.connect(loaded.append)
    view.rerun_requested.connect(rerun.append)

    view.load_into_chat_btn.click()
    view.rerun_btn.click()

    assert loaded == ["row_action"]
    assert rerun == ["row_action"]


def test_search(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_history_manager(view.history_manager.__class__(str(tmp_path / "history.db")))
    view.history_manager.create_task("row_alpha", "Alpha task", "cli")
    view.history_manager.create_task("row_beta", "Beta task", "desktop")

    view.on_search("Beta")

    assert view.table.rowCount() == 1
    assert view.table.item(0, 1).text() == "Beta task"


def test_search_and_status_combined_matches_task_id(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    mgr = view.history_manager.__class__(str(tmp_path / "history.db"))
    view.set_history_manager(mgr)
    view.history_manager.create_task("task_fail_123", "Broken thing", "cli")
    view.history_manager.complete_task("task_fail_123", error_message="error")
    view.history_manager.create_task("task_done_456", "Finished thing", "cli")
    view.history_manager.complete_task("task_done_456")

    view.status_filter.setCurrentText("failed")
    view.search_input.setText("123")

    assert view.table.rowCount() == 1
    assert view.table.item(0, 4).text() == "task_fail_123"


def test_status_filter_shows_only_matching_tasks(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    mgr = view.history_manager.__class__(str(tmp_path / "history.db"))
    view.set_history_manager(mgr)
    view.history_manager.create_task("task_fail", "Broken thing", "cli")
    view.history_manager.complete_task("task_fail", error_message="error")
    view.history_manager.create_task("task_done", "Finished thing", "cli")
    view.history_manager.complete_task("task_done")

    view.status_filter.setCurrentText("failed")

    assert view.table.rowCount() == 1
    assert view.table.item(0, 3).text() == "failed"


def test_clear_filters_resets_all(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    mgr = view.history_manager.__class__(str(tmp_path / "history.db"))
    view.set_history_manager(mgr)
    view.history_manager.create_task("task_a", "Alpha", "cli")
    view.history_manager.create_task("task_b", "Beta", "cli")
    view.history_manager.complete_task("task_a")

    view.search_input.setText("Alpha")
    view.status_filter.setCurrentText("completed")
    assert view.table.rowCount() == 1

    view.clear_filters()
    assert view.table.rowCount() == 2
    assert view.clear_btn.isHidden()
    assert view.filter_label.isHidden()


def test_history_view_clears_detail_pane_when_filter_has_no_results(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    mgr = view.history_manager.__class__(str(tmp_path / "history.db"))
    view.set_history_manager(mgr)
    view.history_manager.create_task("task_visible", "Visible task", "cli")
    view.load_history()

    assert view.detail_task_id.text() == "task_visible"
    assert view.load_into_chat_btn.isEnabled()

    view.search_input.setText("does-not-exist")

    assert view.table.rowCount() == 0
    assert view.detail_summary.text() == "No tasks match this filter."
    assert view.detail_task_id.text() == "-"
    assert not view.load_into_chat_btn.isEnabled()
    assert not view.rerun_btn.isEnabled()


def test_history_view_filter_keeps_explicit_detail_selection(app, qtbot, tmp_path):
    view = HistoryView()
    qtbot.addWidget(view)
    mgr = view.history_manager.__class__(str(tmp_path / "history.db"))
    view.set_history_manager(mgr)
    view.history_manager.create_task("task_alpha", "Alpha task", "cli")
    view.history_manager.create_task("task_beta", "Beta task", "desktop")
    view.load_history()

    assert view.show_task_details("task_alpha")
    view.search_input.setText("Alpha")

    assert view.table.rowCount() == 1
    assert view.table.item(0, 4).text() == "task_alpha"
    assert view.detail_task_id.text() == "task_alpha"
    assert view.detail_summary.text() == "Alpha task"


def test_history_view_import_archive_populates_detail_without_selection_signal(app, qtbot, tmp_path, monkeypatch):
    view = HistoryView()
    qtbot.addWidget(view)
    mgr = view.history_manager.__class__(str(tmp_path / "history.db"))
    view.set_history_manager(mgr)

    archive_path = tmp_path / "history-import.json"
    archive_payload = {
        "version": 1,
        "source_app": "unified-app",
        "tasks": [
            {
                "task_id": "imported_task",
                "description": "Imported desktop task",
                "domain": "desktop",
                "status": "completed",
                "created_at": None,
                "started_at": None,
                "completed_at": None,
                "plan_steps": ["Open app"],
                "result_data": {"ok": True},
                "error_message": None,
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Open app",
                        "status": "completed",
                        "result_data": {"ok": True},
                        "error_message": None,
                        "started_at": None,
                        "completed_at": None,
                        "flight_report_path": None,
                    }
                ],
            }
        ],
    }
    archive_path.write_text(json.dumps(archive_payload), encoding="utf-8")

    messages: list[tuple[str, str]] = []
    selected_rows: list[str] = []

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(archive_path), "JSON files (*.json)")),
    )

    def record_message(title: str, text: str, icon: QMessageBox.Icon) -> None:
        messages.append((title, text))

    monkeypatch.setattr(view, "_show_message_box", record_message)
    monkeypatch.setattr(view, "_select_task_row", lambda task_id: selected_rows.append(task_id))

    view.import_archive()

    assert view.table.rowCount() == 1
    assert selected_rows
    assert selected_rows[-1] == "imported_task"
    assert view.detail_task_id.text() == "imported_task"
    assert view.detail_summary.text() == "Imported desktop task"
    assert "Open app" in view.plan_steps.toPlainText()
    assert messages == [("Import complete", "Imported 1 task(s).")]
