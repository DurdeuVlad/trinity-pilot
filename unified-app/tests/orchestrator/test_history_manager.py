"""Tests for history manager CRUD operations."""
from __future__ import annotations

from pathlib import Path

from orchestrator.database import HistoryManager, TaskStatus


def test_create_start_complete_task(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    task = manager.create_task("task_001", "Test objective", "cli", ["step1"], 10, 0.9)
    assert task.task_id == "task_001"
    manager.start_task("task_001")
    manager.complete_task("task_001", result_data={"ok": True})

    updated = manager.get_task("task_001")
    assert updated is not None
    assert updated.status == TaskStatus.COMPLETED
    manager.close()


def test_steps_and_search(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    manager.create_task("task_abc", "Search files", "cli")
    manager.add_step("task_abc", 1, "List files")
    manager.update_step_status("task_abc", 1, TaskStatus.COMPLETED, result_data={"count": 4})
    found = manager.search_tasks("Search")
    assert len(found) == 1
    assert found[0].task_id == "task_abc"
    manager.close()


def test_get_task_with_steps_returns_normalized_data(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    manager.create_task("task_norm", "Normalize outputs", "mixed", ["Plan A", "Plan B"], 15, 0.8)
    manager.add_step("task_norm", 1, "Collect data")
    manager.update_step_status("task_norm", 1, TaskStatus.COMPLETED, result_data={"rows": 3})
    manager.complete_task("task_norm", result_data={"status": "done"})

    details = manager.get_task_with_steps("task_norm")

    assert details is not None
    assert details["task_id"] == "task_norm"
    assert details["plan_steps"] == ["Plan A", "Plan B"]
    assert details["result_data"] == {"status": "done"}
    assert details["steps"][0]["description"] == "Collect data"
    assert details["steps"][0]["result_data"] == {"rows": 3}
    manager.close()


def test_get_tasks_by_status_returns_matching(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    manager.create_task("t_pending", "Pending task", "cli")
    manager.create_task("t_failed", "Failed task", "cli")
    manager.complete_task("t_failed", error_message="boom")
    results = manager.get_tasks_by_status(TaskStatus.FAILED)
    assert len(results) == 1
    assert results[0].task_id == "t_failed"
    manager.close()


def test_export_archive_includes_steps_and_metadata(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    manager.create_task("task_export", "Export me", "desktop", ["Step one"], 12, 0.7)
    manager.add_step("task_export", 1, "Open app")
    manager.update_step_status("task_export", 1, TaskStatus.COMPLETED, result_data={"ok": True})
    manager.complete_task("task_export", result_data={"finished": True})

    archive = manager.export_archive(task_ids=["task_export"])

    assert archive["version"] == 1
    assert archive["source_app"] == "unified-app"
    assert len(archive["tasks"]) == 1
    task = archive["tasks"][0]
    assert task["task_id"] == "task_export"
    assert task["plan_steps"] == ["Step one"]
    assert task["result_data"] == {"finished": True}
    assert task["steps"][0]["description"] == "Open app"
    assert task["steps"][0]["result_data"] == {"ok": True}
    manager.close()


def test_export_archive_filters_by_status(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    manager.create_task("task_failed", "Broken thing", "cli")
    manager.complete_task("task_failed", error_message="boom")
    manager.create_task("task_done", "Finished thing", "cli")
    manager.complete_task("task_done")

    archive = manager.export_archive(status="failed")

    assert len(archive["tasks"]) == 1
    assert archive["tasks"][0]["task_id"] == "task_failed"
    manager.close()


def test_import_archive_renames_collisions(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    manager.create_task("task_001", "Existing task", "cli")

    archive = {
        "version": 1,
        "exported_at": "2026-03-27T10:00:00+00:00",
        "source_app": "unified-app",
        "tasks": [
            {
                "task_id": "task_001",
                "description": "Imported task",
                "domain": "desktop",
                "status": "completed",
                "created_at": "2026-03-27T11:00:00+00:00",
                "started_at": "2026-03-27T11:01:00+00:00",
                "completed_at": "2026-03-27T11:02:00+00:00",
                "plan_steps": ["Plan 1"],
                "estimated_duration": 10,
                "confidence": 0.9,
                "result_data": {"ok": True},
                "error_message": None,
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Open app",
                        "status": "completed",
                        "started_at": "2026-03-27T11:01:00+00:00",
                        "completed_at": "2026-03-27T11:02:00+00:00",
                        "result_data": {"done": True},
                        "error_message": None,
                        "flight_report_path": None,
                    }
                ],
            }
        ],
    }

    import_result = manager.import_archive(archive)

    assert import_result["task_ids"] == ["task_001-imported-1"]
    imported = manager.get_task_with_steps("task_001-imported-1")
    assert imported is not None
    assert imported["description"] == "Imported task"
    assert imported["steps"][0]["description"] == "Open app"
    manager.close()


def test_import_archive_accepts_json_string_payload(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))
    result = manager.import_archive('{"version": 1, "tasks": []}')
    assert result["imported_count"] == 0
    manager.close()


def test_import_archive_rejects_unknown_version(tmp_path):
    manager = HistoryManager(str(tmp_path / "history.db"))

    archive = {"version": 99, "tasks": []}

    try:
        manager.import_archive(archive)
    except ValueError as exc:
        assert "Unsupported archive version" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected unsupported archive version to raise ValueError")
    finally:
        manager.close()


def test_default_db_path_is_repo_runtime_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    manager = HistoryManager()

    expected = Path(__file__).resolve().parents[2] / "_runtime" / "orchestrator_history.db"
    assert manager.db_path == expected.resolve()
    manager.close()
