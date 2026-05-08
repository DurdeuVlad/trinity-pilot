"""TaskStore.get_task tests."""
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
