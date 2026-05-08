"""TaskStore unit tests."""
from trinity_pilot.core.types import TaskRecord, TaskStatus
from trinity_pilot.memory.store import TaskStore


class TestTaskStoreGetTask:
    def test_get_task_returns_saved_record(self):
        store = TaskStore()
        record = TaskRecord(
            task_id="task-xyz",
            user_request="open google.com",
            status=TaskStatus.RUNNING,
        )
        store.save_task(record)

        loaded = store.get_task("task-xyz")
        assert loaded is not None
        assert loaded.task_id == "task-xyz"
        assert loaded.user_request == "open google.com"
        assert loaded.status == TaskStatus.RUNNING

    def test_get_task_returns_none_for_missing(self):
        store = TaskStore()
        result = store.get_task("nonexistent-id")
        assert result is None

    def test_get_task_reflects_status_update(self):
        store = TaskStore()
        record = TaskRecord(task_id="task-upd", user_request="x", status=TaskStatus.PENDING)
        store.save_task(record)
        store.update_status("task-upd", TaskStatus.COMPLETED)

        loaded = store.get_task("task-upd")
        assert loaded is not None
        assert loaded.status == TaskStatus.COMPLETED


class TestTaskStoreListTasks:
    def test_list_tasks_returns_all(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-1", user_request="req1", status=TaskStatus.PENDING))
        store.save_task(TaskRecord(task_id="t-2", user_request="req2", status=TaskStatus.RUNNING))
        results = store.list_tasks()
        assert len(results) == 2
        ids = {r.task_id for r in results}
        assert ids == {"t-1", "t-2"}

    def test_list_tasks_filters_by_status(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-1", user_request="a", status=TaskStatus.PENDING))
        store.save_task(TaskRecord(task_id="t-2", user_request="b", status=TaskStatus.COMPLETED))
        store.save_task(TaskRecord(task_id="t-3", user_request="c", status=TaskStatus.PENDING))
        running = store.list_tasks(status=TaskStatus.COMPLETED)
        assert len(running) == 1
        assert running[0].task_id == "t-2"

    def test_list_tasks_empty_store(self):
        store = TaskStore()
        assert store.list_tasks() == []

    def test_list_tasks_preserves_user_request(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-req", user_request="open browser and go to example.com", status=TaskStatus.PENDING))
        results = store.list_tasks()
        assert len(results) == 1
        assert results[0].user_request == "open browser and go to example.com"


class TestTaskStoreSearch:
    def test_search_finds_matching_task(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-search-1", user_request="open browser and navigate"))
        results = store.search("browser")
        assert "t-search-1" in results

    def test_search_returns_empty_for_no_match(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-search-2", user_request="open terminal"))
        results = store.search("xyznonexistentquery123")
        assert results == []


class TestTaskStoreUpdateStatus:
    def test_update_status_written_to_db(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-direct", user_request="x", status=TaskStatus.PENDING))
        store.update_status("t-direct", TaskStatus.RUNNING)

        # Query DB directly — bypasses get_task() to confirm row is actually updated
        row = store._conn.execute(
            "SELECT status FROM tasks WHERE task_id=?", ("t-direct",)
        ).fetchone()
        assert row is not None
        assert row["status"] == TaskStatus.RUNNING.value

    def test_update_status_to_cancelled(self):
        store = TaskStore()
        store.save_task(TaskRecord(task_id="t-cancel", user_request="y", status=TaskStatus.RUNNING))
        store.update_status("t-cancel", TaskStatus.CANCELLED)

        row = store._conn.execute(
            "SELECT status FROM tasks WHERE task_id=?", ("t-cancel",)
        ).fetchone()
        assert row["status"] == TaskStatus.CANCELLED.value
