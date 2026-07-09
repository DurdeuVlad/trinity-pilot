from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal

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
        signals_queue: asyncio.Queue | None = None,
    ) -> None:
        super().__init__()
        self._user_request = user_request
        self._task_id = task_id
        self._settings = settings
        self._db_path = db_path
        self._objectives = objectives
        self._signals: asyncio.Queue | None = signals_queue
        self._loop: asyncio.AbstractEventLoop | None = None
        self._orchestrator: AsyncTaskOrchestrator | None = None
        self._cancel_requested = False

    def run(self) -> None:
        # Initialize COM in STA mode on this thread before the asyncio loop starts.
        # pywinauto uses UIA (COM-based) for window automation; if the calling thread
        # hasn't called CoInitialize(STA), COM raises RPC_E_WRONG_THREAD (0x8001010d)
        # and crashes the process.  This must be called once per thread before any UIA use.
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            result = self._loop.run_until_complete(self._run_orchestrator())
            self.task_finished.emit(self._task_id, result)
        except BaseException as exc:  # noqa: BLE001 — catch everything, incl. KeyboardInterrupt
            import traceback as _tb
            full_trace = _tb.format_exc()
            self.log_message.emit(f"[CRASH] {exc}\n{full_trace}")
            # Save crash bundle to disk.
            try:
                from trinity_pilot.__main__ import _write_crash, _ensure_crashes_dir
                _write_crash(f"worker-{self._task_id}", full_trace, _ensure_crashes_dir())
            except Exception:
                pass
            self.task_finished.emit(self._task_id, {
                "task_id": self._task_id,
                "status": "crashed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": full_trace,
            })
        finally:
            self._loop.close()
            try:
                import comtypes
                comtypes.CoUninitialize()
            except Exception:
                pass

    async def _drain_signals(self, queue: asyncio.Queue) -> None:
        """Drain orchestrator signals into the trace log until cancelled."""
        from trinity_pilot.telemetry.trace import emit_signal

        while True:
            try:
                signal = await asyncio.wait_for(queue.get(), timeout=0.25)
                emit_signal(signal)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _run_orchestrator(self) -> dict:
        from trinity_pilot.telemetry.trace import emit

        signals_queue = self._signals if self._signals is not None else asyncio.Queue()
        self._orchestrator = AsyncTaskOrchestrator(
            self._settings,
            db_path=self._db_path,
            signals=signals_queue,
        )
        if self._cancel_requested:
            self._orchestrator.cancel()
        emit(
            "bridge.py:_run_orchestrator",
            "task_started",
            {"task_id": self._task_id},
            span="bridge",
        )
        self.log_message.emit(f"[ORCHESTRATOR] Task started: {self._task_id}")
        drain_task = asyncio.create_task(self._drain_signals(signals_queue))
        run_task = asyncio.create_task(
            self._orchestrator.run(
                self._user_request,
                task_id=self._task_id,
                objectives=self._objectives,
            )
        )
        try:
            while not run_task.done():
                await asyncio.sleep(0.25)
                self.status_changed.emit(self._orchestrator.snapshot.status.value)
            result = await run_task
            emit(
                "bridge.py:_run_orchestrator",
                "task_finished",
                {"task_id": self._task_id, "status": result.get("status")},
                span="bridge",
            )
            return result
        finally:
            drain_task.cancel()
            try:
                await drain_task
            except asyncio.CancelledError:
                pass

    def request_cancel(self) -> None:
        self._cancel_requested = True
        if self._loop and self._orchestrator:
            self._loop.call_soon_threadsafe(self._orchestrator.cancel)


class _SingleAgentWorkerThread(QThread):
    """QThread that runs SingleAgentWorker directly — no Planner, no Reviewer."""
    status_changed = Signal(str)
    log_message = Signal(str)
    task_finished = Signal(str, object)  # task_id, result dict

    _orchestrator = None  # satisfies WorkflowBridge.query_progress() guard

    def request_cancel(self) -> None:
        pass  # no cancellation mechanism in single-agent mode; thread runs to completion

    def __init__(self, user_request: str, task_id: str, settings: "Settings", db_path: str) -> None:
        super().__init__()
        self._user_request = user_request
        self._task_id = task_id
        self._settings = settings
        self._db_path = db_path
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            result = self._loop.run_until_complete(self._run_single_agent())
            self.task_finished.emit(self._task_id, result)
        except BaseException as exc:  # noqa: BLE001
            import traceback as _tb
            full_trace = _tb.format_exc()
            self.log_message.emit(f"[SA-CRASH] {exc}\n{full_trace}")
            self.task_finished.emit(self._task_id, {
                "task_id": self._task_id,
                "status": "crashed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": full_trace,
                "single_agent_summary": "",
            })
        finally:
            self._loop.close()
            try:
                import comtypes
                comtypes.CoUninitialize()
            except Exception:
                pass

    async def _run_single_agent(self) -> dict:
        from trinity_pilot.workers.single_agent_worker import SingleAgentWorker
        self.status_changed.emit("executing")
        self.log_message.emit(f"[SA] Task started: {self._task_id}")
        worker = SingleAgentWorker()
        result = await worker.execute_raw(self._user_request)
        status = "completed" if result.status == "success" else "failed"
        self.log_message.emit(f"[SA] Task finished: status={status}")
        return {
            "task_id": self._task_id,
            "status": status,
            "results": {},
            "single_agent_summary": result.summary,
            "error": result.summary if status == "failed" else "",
        }


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
        signals_queue: asyncio.Queue | None = None,
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
            signals_queue,
        )
        if on_log:
            self._worker.log_message.connect(on_log)
        if on_status:
            self._worker.status_changed.connect(on_status)
        if on_done:
            self._worker.task_finished.connect(
                lambda tid, result: on_done(result),
                Qt.ConnectionType.QueuedConnection,
            )
        self._worker.task_finished.connect(
            self._on_worker_finished,
            Qt.ConnectionType.QueuedConnection,
        )
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
        import time as _time

        from trinity_pilot._agent_debug import agent_dbg

        agent_dbg(
            "bridge.py:plan_only",
            "plan_only_invoked",
            {"request_len": len(user_request), "request_preview": user_request[:120]},
            hypothesis_id="H1-planner-hang",
        )

        def _run() -> None:
            t0 = _time.monotonic()
            try:
                import asyncio
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.planner.planner import ObjectivePlanner

                agent_dbg(
                    "bridge.py:plan_only",
                    "planner_thread_started",
                    {"model": os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash")},
                    hypothesis_id="H1-planner-hang",
                )
                provider = GeminiProvider(
                    api_key=os.environ["GEMINI_API_KEY"],
                    model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash"),
                )
                planner = ObjectivePlanner(provider=provider)
                loop = asyncio.new_event_loop()
                try:
                    specs = loop.run_until_complete(planner.plan(user_request))
                    spec_dicts = [s.to_dict() for s in specs]
                    agent_dbg(
                        "bridge.py:plan_only",
                        "planner_thread_done",
                        {
                            "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                            "n_specs": len(spec_dicts),
                            "objective_ids": [s.get("objective_id") for s in spec_dicts],
                        },
                        hypothesis_id="H1-planner-hang",
                    )
                    if on_planned:
                        on_planned(spec_dicts)
                except Exception as exc:  # noqa: BLE001
                    agent_dbg(
                        "bridge.py:plan_only",
                        "planner_thread_error",
                        {
                            "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                            "error": str(exc)[:500],
                        },
                        hypothesis_id="H1-planner-hang",
                    )
                    if on_error:
                        on_error(str(exc))
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                agent_dbg(
                    "bridge.py:plan_only",
                    "planner_thread_outer_error",
                    {
                        "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                        "error": str(exc)[:500],
                    },
                    hypothesis_id="H1-planner-hang",
                )
                if on_error:
                    on_error(str(exc))

        t = threading.Thread(target=_run, daemon=True, name="trinity-planner")
        t.start()

    def start_task_single_agent(
        self,
        user_request: str,
        on_log: "Callable[[str], None] | None" = None,
        on_status: "Callable[[str], None] | None" = None,
        on_done: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> str:
        """Start a single-agent task (ablation mode). No planning, no confirm step."""
        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            user_request=user_request,
            objectives=[],
            status=TaskStatus.RUNNING,
        )
        self._store.save_task(record)

        self._worker = _SingleAgentWorkerThread(
            user_request, task_id, self._settings, self._store_path
        )
        if on_log:
            self._worker.log_message.connect(on_log)
        if on_status:
            self._worker.status_changed.connect(on_status)
        if on_done:
            self._worker.task_finished.connect(
                lambda tid, result: on_done(result),
                Qt.ConnectionType.QueuedConnection,
            )
        self._worker.task_finished.connect(
            self._on_worker_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._worker.start()
        return task_id

    def stop_task(self, wait_ms: int = 5000) -> None:
        """Request cancellation and wait for the worker thread to finish.

        wait_ms: max milliseconds to wait for the thread to exit (default 5 s).
        Waiting is essential in tests so the COM apartment from the previous
        worker is fully torn down before the next test creates a new one.
        """
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()
            self._worker.wait(wait_ms)  # blocks until thread exits or timeout

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
