from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from trinity_pilot.config import Settings
from trinity_pilot.core.types import ObjectiveSpec, TaskRecord, TaskStatus
from trinity_pilot.memory.store import TaskStore
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator


class _WorkerThread(QThread):
    status_changed = Signal(str)
    log_message = Signal(str)
    task_finished = Signal(str, object)  # task_id, result dict

    def __init__(
        self,
        user_request: str,
        task_id: str,
        settings: Settings,
        db_path: str,
        objectives: list[ObjectiveSpec] | None = None,
    ) -> None:
        super().__init__()
        self._user_request = user_request
        self._task_id = task_id
        self._settings = settings
        self._db_path = db_path
        self._objectives = objectives
        self._loop: asyncio.AbstractEventLoop | None = None
        self._orchestrator: AsyncTaskOrchestrator | None = None
        self._cancel_requested = False

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            result = self._loop.run_until_complete(self._run_orchestrator())
            self.task_finished.emit(self._task_id, result)
        except Exception as exc:
            self.log_message.emit(f"[ERROR] {exc}")
            self.task_finished.emit(self._task_id, {"task_id": self._task_id, "status": "failed", "error": str(exc)})
        finally:
            self._loop.close()

    async def _run_orchestrator(self) -> dict:
        self._orchestrator = AsyncTaskOrchestrator(
            self._settings,
            db_path=self._db_path,
        )
        if self._cancel_requested:
            self._orchestrator.cancel()
        self.log_message.emit(f"[ORCHESTRATOR] Task started: {self._task_id}")
        run_task = asyncio.create_task(
            self._orchestrator.run(
                self._user_request,
                task_id=self._task_id,
                objectives=self._objectives,
            )
        )
        while not run_task.done():
            await asyncio.sleep(0.25)
            self.status_changed.emit(self._orchestrator.snapshot.status.value)
        return await run_task

    def request_cancel(self) -> None:
        self._cancel_requested = True
        if self._loop and self._orchestrator:
            self._loop.call_soon_threadsafe(self._orchestrator.cancel)


class WorkflowBridge(QObject):
    """Connects MainWindow submit/stop events to local asyncio orchestration."""

    def __init__(self, settings: Settings, db_path: str = "trinity_pilot.db") -> None:
        super().__init__()
        self._settings = settings
        self._store_path = db_path
        self._store = TaskStore(db_path)
        self._worker: _WorkerThread | None = None

    def start_task(
        self,
        user_request: str,
        on_log: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_done: Callable[[dict[str, Any]], None] | None = None,
        objectives: list[dict] | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        objective_specs = [ObjectiveSpec.from_dict(o) for o in objectives] if objectives else []
        record = TaskRecord(
            task_id=task_id,
            user_request=user_request,
            objectives=objective_specs,
            status=TaskStatus.RUNNING,
        )
        self._store.save_task(record)

        self._worker = _WorkerThread(
            user_request,
            task_id,
            self._settings,
            self._store_path,
            objective_specs or None,
        )
        if on_log:
            self._worker.log_message.connect(on_log)
        if on_status:
            self._worker.status_changed.connect(on_status)
        if on_done:
            self._worker.task_finished.connect(
                lambda tid, result: on_done(result)
            )
        self._worker.task_finished.connect(self._on_worker_finished)
        self._worker.start()
        return task_id

    def plan_only(
        self,
        user_request: str,
        on_planned: Callable[[list[dict]], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Run the planner in a background thread and return specs via callback."""
        import threading
        import os

        def _run() -> None:
            try:
                import asyncio
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.planner.planner import ObjectivePlanner

                provider = GeminiProvider(
                    api_key=os.environ["GEMINI_API_KEY"],
                    model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.0-flash"),
                )
                planner = ObjectivePlanner(provider=provider)
                loop = asyncio.new_event_loop()
                try:
                    specs = loop.run_until_complete(planner.plan(user_request))
                    spec_dicts = [s.to_dict() for s in specs]
                    if on_planned:
                        on_planned(spec_dicts)
                except Exception as exc:  # noqa: BLE001
                    if on_error:
                        on_error(str(exc))
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                if on_error:
                    on_error(str(exc))

        t = threading.Thread(target=_run, daemon=True, name="trinity-planner")
        t.start()

    def stop_task(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()

    def query_progress(self) -> dict:
        """Return {current_objective, completed_objectives} from the active orchestrator.

        Safe to call from the Qt main thread while a worker is running.
        Returns an empty dict if no active orchestrator is available.
        """
        worker = self._worker
        if not worker or not worker.isRunning():
            return {}
        orchestrator = worker._orchestrator
        if not orchestrator:
            return {}
        snapshot = orchestrator.snapshot
        return {
            "current_objective": snapshot.current_objective,
            "completed_objectives": snapshot.completed_objectives,
        }

    def _on_worker_finished(self, task_id: str, result: object) -> None:
        final_status = result.get("status", "failed") if isinstance(result, dict) else str(result)
        try:
            status = TaskStatus(final_status)
        except ValueError:
            status = TaskStatus.FAILED
        self._store.update_status(task_id, status)
