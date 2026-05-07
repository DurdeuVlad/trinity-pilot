from __future__ import annotations

import asyncio
import uuid
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from trinity_pilot.config import Settings
from trinity_pilot.core.types import TaskRecord, TaskStatus
from trinity_pilot.memory.store import TaskStore


class _WorkerThread(QThread):
    status_changed = Signal(str)
    log_message = Signal(str)
    task_finished = Signal(str, str)  # task_id, final_status

    def __init__(self, user_request: str, task_id: str, settings: Settings) -> None:
        super().__init__()
        self._user_request = user_request
        self._task_id = task_id
        self._settings = settings
        self._loop: asyncio.AbstractEventLoop | None = None
        self._workflow_handle = None

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            result = self._loop.run_until_complete(self._run_workflow())
            self.task_finished.emit(self._task_id, result.get("status", "unknown"))
        except Exception as exc:
            self.log_message.emit(f"[ERROR] {exc}")
            self.task_finished.emit(self._task_id, "error")
        finally:
            self._loop.close()

    async def _run_workflow(self) -> dict:
        from temporalio.client import Client
        from trinity_pilot.workflow.task_workflow import TaskWorkflow

        client = await Client.connect(self._settings.temporal_host)
        handle = await client.start_workflow(
            TaskWorkflow.run,
            self._user_request,
            id=self._task_id,
            task_queue="trinity-pilot",
        )
        self._workflow_handle = handle
        self.log_message.emit(f"[TEMPORAL] Workflow started: {self._task_id}")

        while True:
            await asyncio.sleep(2)
            try:
                status: str = await handle.query(TaskWorkflow.get_status)
                self.status_changed.emit(status)
                if status in ("cancelled",):
                    return {"status": status}
            except Exception:
                break

        result = await handle.result()
        return result

    def request_cancel(self) -> None:
        if self._workflow_handle and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._workflow_handle.signal(TaskWorkflow.cancel),
                self._loop,
            )


class WorkflowBridge(QObject):
    """Connects MainWindow submit/stop events to Temporal workflow execution."""

    def __init__(self, settings: Settings, db_path: str = "trinity_pilot.db") -> None:
        super().__init__()
        self._settings = settings
        self._store = TaskStore(db_path)
        self._worker: _WorkerThread | None = None

    def start_task(
        self,
        user_request: str,
        on_log: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_done: Callable[[str], None] | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            user_request=user_request,
            status=TaskStatus.RUNNING,
        )
        self._store.save_task(record)

        self._worker = _WorkerThread(user_request, task_id, self._settings)
        if on_log:
            self._worker.log_message.connect(on_log)
        if on_status:
            self._worker.status_changed.connect(on_status)
        if on_done:
            self._worker.task_finished.connect(
                lambda tid, s: on_done(s)
            )
        self._worker.task_finished.connect(self._on_worker_finished)
        self._worker.start()
        return task_id

    def stop_task(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()

    def _on_worker_finished(self, task_id: str, final_status: str) -> None:
        try:
            status = TaskStatus(final_status)
        except ValueError:
            status = TaskStatus.FAILED
        self._store.update_status(task_id, status)
