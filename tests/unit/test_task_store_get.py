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
