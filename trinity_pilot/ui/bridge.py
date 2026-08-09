from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from trinity_pilot.config import Settings
from trinity_pilot.core.types import ObjectiveSpec, TaskRecord, TaskStatus
from trinity_pilot.memory.store import TaskStore
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator


class _WorkerThread(QThread):
    status_changed = Signal(str)
    log_message = Signal(str)
    task_finished = Signal(str, object)  # task_id, result dict
    step_signal = Signal(object)  # orchestrator Signal instance (see orchestrator/signals.py)

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
        except Exception as exc:
            # Best-effort: comtypes raises if COM is already initialized on this
            # thread (harmless) or is unavailable (non-Windows). Not fatal either way.
            from trinity_pilot.telemetry.trace import emit as _trace_emit
            _trace_emit("bridge.py:_WorkerThread.run", "com_initialize_failed", {"error": str(exc)})
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
                from trinity_pilot.__main__ import _ensure_crashes_dir, _write_crash
                _write_crash(f"worker-{self._task_id}", full_trace, _ensure_crashes_dir())
            except Exception as write_exc:
                # Best-effort: crash bundle write must never mask the original crash.
                print(f"[bridge] failed to write crash bundle: {write_exc}", file=sys.stderr)
            self.status_changed.emit("crashed")
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
            except Exception as uninit_exc:
                # Best-effort: teardown failure here doesn't affect the result already emitted.
                print(f"[bridge] CoUninitialize failed: {uninit_exc}", file=sys.stderr)

    async def _drain_signals(self, queue: asyncio.Queue) -> None:
        """Drain orchestrator signals into the trace log until cancelled."""
        from trinity_pilot.telemetry.trace import emit_signal

        while True:
            try:
                signal = await asyncio.wait_for(queue.get(), timeout=0.25)
                emit_signal(signal)
                self.step_signal.emit(signal)
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
        self.status_changed.emit("running")
        drain_task = asyncio.create_task(self._drain_signals(signals_queue))
        run_task = asyncio.create_task(
            self._orchestrator.run(
                self._user_request,
                task_id=self._task_id,
                objectives=self._objectives,
            )
        )
        try:
            result = await run_task
            status = str(result.get("status") or "unknown")
            self.status_changed.emit(status)
            emit(
                "bridge.py:_run_orchestrator",
                "task_finished",
                {"task_id": self._task_id, "status": status},
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
            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._orchestrator.cancel)
            except RuntimeError:
                # The worker can finish between the is_closed check and the
                # thread-safe callback.  Cancellation is still represented by
                # _cancel_requested and will be applied if a new run starts.
                pass


class _GuiCallbackRelay(QObject):
    """Deliver worker results to callbacks on the Qt object's owning thread.

    The worker signal is connected to these slots with QueuedConnection.  The
    slots therefore run in the main Qt thread, and only then invoke the UI
    callback.  Headless callers do not use this relay; their callback wiring
    remains synchronous for the existing test harness contract.
    """

    log = Signal(str)
    status = Signal(str)
    done = Signal(object)

    def __init__(
        self,
        parent: QObject,
        *,
        on_log: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_done: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(parent)
        if on_log:
            self.log.connect(on_log, Qt.ConnectionType.DirectConnection)
        if on_status:
            self.status.connect(on_status, Qt.ConnectionType.DirectConnection)
        if on_done:
            self.done.connect(on_done, Qt.ConnectionType.DirectConnection)

    @Slot(str)
    def forward_log(self, message: str) -> None:
        self.log.emit(message)

    @Slot(str)
    def forward_status(self, status: str) -> None:
        self.status.emit(status)

    @Slot(str, object)
    def forward_done(self, _task_id: str, result: object) -> None:
        self.done.emit(result)




class WorkflowBridge(QObject):
    """Connects MainWindow submit/stop events to local asyncio orchestration."""

    # Forwards every orchestrator Signal (WorkerStepSignal, ObjectiveStarted, ...)
    # to the Qt main thread, for live action visualization. Purely additive —
    # no effect on task execution if nothing is connected.
    step_occurred = Signal(object)

    def __init__(self, settings: Settings, db_path: str = "trinity_pilot.db") -> None:
        super().__init__()
        self._settings = settings
        self._store_path = db_path
        self._store = TaskStore(db_path)
        self._worker: _WorkerThread | None = None
        self._gui_relay: _GuiCallbackRelay | None = None

    def start_task(
        self,
        user_request: str,
        on_log: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        on_done: Callable[[dict[str, Any]], None] | None = None,
        objectives: list[dict] | None = None,
        signals_queue: asyncio.Queue | None = None,
        main_thread_callbacks: bool = False,
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

        # Guard against overlapping worker threads: normally the UI disables
        # submission while a task runs, but replacing self._worker here without
        # waiting for the prior thread to actually finish would let two
        # _WorkerThreads run concurrently if that guard is ever bypassed.
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)

        self._worker = _WorkerThread(
            user_request,
            task_id,
            self._settings,
            self._store_path,
            objective_specs or None,
            signals_queue,
        )
        if main_thread_callbacks:
            # Keep the relay owned by WorkflowBridge (the Qt main thread).  A
            # queued connection to a main-thread QObject cannot execute UI
            # code on the worker, even when the worker exits immediately.
            if self._gui_relay is not None:
                self._gui_relay.deleteLater()
            self._gui_relay = _GuiCallbackRelay(
                self,
                on_log=on_log,
                on_status=on_status,
                on_done=on_done,
            )
            if on_log:
                self._worker.log_message.connect(
                    self._gui_relay.forward_log,
                    Qt.ConnectionType.QueuedConnection,
                )
            if on_status:
                self._worker.status_changed.connect(
                    self._gui_relay.forward_status,
                    Qt.ConnectionType.QueuedConnection,
                )
            if on_done:
                self._worker.task_finished.connect(
                    self._gui_relay.forward_done,
                    Qt.ConnectionType.QueuedConnection,
                )
        else:
            # BridgeTestHarness and other headless callers rely on callback
            # delivery being synchronous when no Qt event loop is running.
            if on_log:
                self._worker.log_message.connect(
                    on_log,
                    Qt.ConnectionType.DirectConnection,
                )
            if on_status:
                self._worker.status_changed.connect(
                    on_status,
                    Qt.ConnectionType.DirectConnection,
                )
            if on_done:
                self._worker.task_finished.connect(
                    lambda tid, result: on_done(result),
                    Qt.ConnectionType.DirectConnection,
                )
        self._worker.task_finished.connect(
            self._on_worker_finished,
            Qt.ConnectionType.DirectConnection,
        )
        # Always wired (independent of main_thread_callbacks): live action
        # visualization is opt-in on the listener side (nothing connects to
        # step_occurred unless a UI panel subscribes to it). Guarded with
        # getattr so test doubles that stand in for _WorkerThread without
        # this signal keep working.
        step_signal = getattr(self._worker, "step_signal", None)
        if step_signal is not None:
            step_signal.connect(
                self.step_occurred.emit,
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
        import time as _time

        from trinity_pilot.telemetry.trace import emit

        emit(
            "bridge.py:plan_only",
            "plan_only_invoked",
            {"request_len": len(user_request), "request_preview": user_request[:120]},
        )

        def _run() -> None:
            t0 = _time.monotonic()
            try:
                import asyncio

                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.planner.planner import ObjectivePlanner

                emit(
                    "bridge.py:plan_only",
                    "planner_thread_started",
                    {"model": self._settings.gemini_planner_model},
                )
                provider = GeminiProvider(
                    api_key=self._settings.gemini_api_key,
                    model=self._settings.gemini_planner_model,
                )
                planner = ObjectivePlanner(provider=provider)
                loop = asyncio.new_event_loop()
                try:
                    specs = loop.run_until_complete(planner.plan(user_request))
                    spec_dicts = [s.to_dict() for s in specs]
                    emit(
                        "bridge.py:plan_only",
                        "planner_thread_done",
                        {
                            "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                            "n_specs": len(spec_dicts),
                            "objective_ids": [s.get("objective_id") for s in spec_dicts],
                        },
                    )
                    if on_planned:
                        on_planned(spec_dicts)
                except Exception as exc:  # noqa: BLE001
                    emit(
                        "bridge.py:plan_only",
                        "planner_thread_error",
                        {
                            "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                            "error": str(exc)[:500],
                        },
                    )
                    if on_error:
                        on_error(str(exc))
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                emit(
                    "bridge.py:plan_only",
                    "planner_thread_outer_error",
                    {
                        "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                        "error": str(exc)[:500],
                    },
                )
                if on_error:
                    on_error(str(exc))

        t = threading.Thread(target=_run, daemon=True, name="trinity-planner")
        t.start()


    def stop_task(self, wait_ms: int = 0) -> bool:
        """Request cancellation without blocking the Qt event loop.

        ``wait_ms`` is an opt-in teardown wait for headless tests.  The UI uses
        the default so the worker can unwind its asyncio/MCP cancellation while
        Qt continues processing queued completion signals.
        """
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()
            if wait_ms > 0:
                self._worker.wait(wait_ms)  # optional; never required by the UI
            return True
        return False

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
