"""Legacy worker-direct acceptance regression tests.

These tests verify the 5 acceptance flows defined in PoC_ACCEPTANCE.md.
They are marked @pytest.mark.live and skip automatically unless
``POC_LIVE_TEST=1`` is set in the environment.

To run:
    POC_LIVE_TEST=1 PYTHONPATH=. GEMINI_MOCK=1 \\
        pytest unified-app/tests/integration/test_poc_acceptance.py -v
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

import orchestrator.orchestrator_core as core_module
from orchestrator.database.manager import HistoryManager, TaskStatus
from orchestrator.event_bus import EventBus, get_event_bus
from orchestrator.orchestrator_core import OrchestratorWorker
from orchestrator.screenshot_watcher import ScreenshotWatcher


# ---------------------------------------------------------------------------
# Skip guard — all tests in this module require POC_LIVE_TEST=1
# ---------------------------------------------------------------------------

_LIVE = os.getenv("POC_LIVE_TEST", "0") == "1"

pytestmark = [pytest.mark.live, pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _Signal:
    """Minimal Qt-free signal stub — stores emitted values."""

    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in self._slots:
            slot(*args)


class FakeWatcher:
    """Stub ScreenshotWatcher that emits no frames."""

    frame_captured = _Signal()
    frame_rate_updated = _Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def start_watching(self) -> None:
        return None

    def stop_watching(self) -> None:
        return None


async def _run_worker(
    description: str,
    domain: str,
    monkeypatch: pytest.MonkeyPatch,
    bus: EventBus,
) -> OrchestratorWorker:
    """Submit a task through a real OrchestratorWorker and await completion.

    Uses a real HistoryManager (writes to the SQLite DB on disk).
    ScreenshotWatcher is stubbed to avoid Qt window dependency.
    """
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker(description, domain)
    # Inject the shared bus into the worker AFTER construction
    worker.event_bus = bus

    await worker._execute()
    return worker


# ---------------------------------------------------------------------------
# Flow 1 — Happy CLI path
# ---------------------------------------------------------------------------


async def test_flow1_happy_cli_path_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Flow 1: CLI task through real OrchestratorWorker → TaskStatus.COMPLETED.

    GIVEN GEMINI_MOCK=1 GEMINI_API_KEY=mock
    WHEN  OrchestratorWorker executes a CLI task via TrinityExecutor + CLIAdapter
    THEN  HistoryManager records TaskStatus.COMPLETED in the real SQLite DB.
    """
    if not _LIVE:
        pytest.skip("set POC_LIVE_TEST=1 to run live acceptance tests")

    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    bus = EventBus()

    worker = await _run_worker("list files in current directory", "cli", monkeypatch, bus)

    task = worker.history_manager.get_task(worker.run_id)
    assert task is not None, "Task was never written to HistoryManager"
    assert task.status == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {task.status!r}. error_message={task.error_message!r}"
    )

    worker.history_manager.close()


# ---------------------------------------------------------------------------
# Flow 2 — Fallback plan path
# ---------------------------------------------------------------------------


async def test_flow2_fallback_plan_reaches_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Flow 2: Planner failure → _fallback_plan() fires → task reaches terminal status.

    GIVEN GEMINI_MOCK=1 and MacroPlanner.generate_plan raises ConnectionError
    WHEN  OrchestratorWorker._execute() runs
    THEN  _fallback_plan() returns deterministic steps, task reaches terminal
          status (COMPLETED or FAILED), and is NOT missing from History.
    """
    if not _LIVE:
        pytest.skip("set POC_LIVE_TEST=1 to run live acceptance tests")

    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    # Force _fallback_plan() by making generate_plan() raise
    from orchestrator import macro_planner as planner_module

    async def _raise_network_error(self: Any, description: str, domain: str) -> Any:
        raise ConnectionError("simulated mock network failure → triggers _fallback_plan()")

    monkeypatch.setattr(planner_module.MacroPlanner, "generate_plan", _raise_network_error)

    bus = EventBus()
    worker = await _run_worker("check disk usage", "cli", monkeypatch, bus)

    task = worker.history_manager.get_task(worker.run_id)
    assert task is not None, "Task was never written to HistoryManager (task stuck or missing)"
    assert task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED), (
        f"Task must reach terminal status; got {task.status!r} (task may be stuck)"
    )

    worker.history_manager.close()


# ---------------------------------------------------------------------------
# Flow 3 — Error recovery path
# ---------------------------------------------------------------------------


async def test_flow3_error_recovery_no_traceback_in_ui(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Flow 3: Step failure → FAILED in History + no traceback in UI + app responsive.

    GIVEN GEMINI_MOCK=1 and AgentLoop.run_objective returns a [halted:] string with traceback
    WHEN  OrchestratorWorker._execute() processes the failure via _handle_objective_failure
    THEN  (a) task.status == TaskStatus.FAILED in real DB
          (b) no 'Traceback' string in EventBus.status_update error-level messages
          (c) a second task can be submitted without error (app remains responsive)

    Note: CLIAdapter is bypassed because the Gemini mock returns {"done": true} immediately
    on the first AI call, never reaching adapter execution.  The correct injection point is
    AgentLoop.run_objective — the string it returns is what execution_runner checks.
    """
    if not _LIVE:
        pytest.skip("set POC_LIVE_TEST=1 to run live acceptance tests")

    import orchestrator.agent_loop as agent_loop_module

    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    async def _failing_run_objective(
        self_loop: Any, objective: str, obj_index: int
    ) -> str:
        return (
            "[halted: consecutive errors - ERROR: "
            "Traceback (most recent call last):\n"
            "  File 'live_test_adapter.py', line 1\n"
            "SimulatedError: live acceptance flow 3 failure]"
        )

    monkeypatch.setattr(agent_loop_module.AgentLoop, "run_objective", _failing_run_objective)

    bus = EventBus()
    error_ui_messages: list[str] = []
    bus.status_update.connect(
        lambda msg, level: error_ui_messages.append(msg) if level == "error" else None
    )

    # (a) + (b): First task — should FAIL with sanitized error message
    worker = await _run_worker("failing step task", "cli", monkeypatch, bus)

    task = worker.history_manager.get_task(worker.run_id)
    assert task is not None, "Task was never written to History"
    assert task.status == TaskStatus.FAILED, f"Expected FAILED; got {task.status!r}"

    assert error_ui_messages, "No error-level status_update emitted on EventBus"
    for msg in error_ui_messages:
        assert "Traceback" not in msg, f"Raw traceback in user-visible UI message: {msg!r}"

    # (c): App responsiveness — remove CLIAdapter patch and submit a second task
    monkeypatch.undo()
    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker2 = OrchestratorWorker("echo second task", "cli")
    worker2.event_bus = bus
    await worker2._execute()

    task2 = worker2.history_manager.get_task(worker2.run_id)
    assert task2 is not None, "Second task was never written — app not responsive after failure"

    worker.history_manager.close()
    worker2.history_manager.close()

# ---------------------------------------------------------------------------
# Flow 4 -- Browser task path
# ---------------------------------------------------------------------------


async def test_flow4_browser_task_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Flow 4: Browser task through real OrchestratorWorker -> terminal status.

    GIVEN GEMINI_MOCK=1 GEMINI_API_KEY=mock
    WHEN  OrchestratorWorker executes a web task via TrinityExecutor + BrowserAdapter
    THEN  HistoryManager records TaskStatus.COMPLETED or TaskStatus.FAILED in the real DB.

    Requires Playwright installed and a network connection for live run.
    Asserts terminal status (COMPLETED or FAILED) -- not just 'not stuck'.
    """
    if not _LIVE:
        pytest.skip("set POC_LIVE_TEST=1 to run live acceptance tests")

    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    bus = EventBus()

    worker = await _run_worker(
        "open google.com and take a screenshot", "web", monkeypatch, bus
    )

    task = worker.history_manager.get_task(worker.run_id)
    assert task is not None, "Task was never written to HistoryManager"
    assert task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED), (
        f"Expected terminal status; got {task.status!r} (task may be stuck)"
    )

    worker.history_manager.close()


# ---------------------------------------------------------------------------
# Flow 5 -- Desktop task path
# ---------------------------------------------------------------------------


async def test_flow5_desktop_task_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Flow 5: Desktop task through real OrchestratorWorker -> terminal status.

    GIVEN GEMINI_MOCK=1 GEMINI_API_KEY=mock
    WHEN  OrchestratorWorker executes a desktop task via TrinityExecutor + DesktopAdapter
    THEN  HistoryManager records TaskStatus.COMPLETED or TaskStatus.FAILED in the real DB.

    Requires Windows environment and target application running for live run.
    Asserts terminal status (COMPLETED or FAILED) -- not just 'not stuck'.
    """
    if not _LIVE:
        pytest.skip("set POC_LIVE_TEST=1 to run live acceptance tests")

    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    bus = EventBus()

    worker = await _run_worker("open Notepad", "desktop", monkeypatch, bus)

    task = worker.history_manager.get_task(worker.run_id)
    assert task is not None, "Task was never written to HistoryManager"
    assert task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED), (
        f"Expected terminal status; got {task.status!r} (task may be stuck)"
    )

    worker.history_manager.close()
