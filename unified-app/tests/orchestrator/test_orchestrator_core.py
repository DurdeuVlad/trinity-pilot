"""Tests for orchestrator worker async flow."""
from __future__ import annotations

import asyncio
import json

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

import orchestrator.orchestrator_core as core_module
from orchestrator.event_bus import EventBus
from orchestrator.macro_planner import ExecutionPlan, PlanStep
from orchestrator.orchestrator_core import OrchestratorCore, OrchestratorWorker


def _is_reflection_call(messages: list[dict]) -> bool:
    system = messages[0].get("content", "") if messages else ""
    return "achieved" in system and "critique" in system


class FakeProvider:
    """Instant-done LLMProvider stub — returns right JSON for action and reflection calls."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        if _is_reflection_call(messages):
            return json.dumps({"achieved": True, "confidence": 0.95, "critique": None})
        return json.dumps({
            "rationale": "done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "objective complete",
        })

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class FakePlanner:
    def __init__(self, provider=None, registry=None) -> None:
        pass

    async def generate_plan(self, _description: str, domain: str) -> ExecutionPlan:
        return ExecutionPlan(
            description="demo",
            domain=domain,
            steps=["step a", "step b"],
            estimated_duration=20,
            confidence=0.9,
        )

    async def replan(self, original_task, completed, failed, remaining) -> list[str]:
        return remaining


class FakeBridge:
    async def initialize(self) -> None:
        return None

    async def execute_task(self, task_id, description, domain, **kwargs):
        return _FakeResult(task_id=task_id, status="success")

    async def shutdown(self) -> None:
        return None


class _FakeResult:
    def __init__(self, task_id: str, status: str = "success") -> None:
        self.task_id = task_id
        self.status = status
        self.output = "ok"
        self.error = None

    def model_dump(self) -> dict:
        return {"task_id": self.task_id, "status": self.status}


class FakeHistoryManager:
    def create_task(self, *args, **kwargs):
        return None

    def start_task(self, *args, **kwargs):
        return None

    def complete_task(self, *args, **kwargs):
        return None

    def add_step(self, *args, **kwargs):
        return None

    def update_step_status(self, *args, **kwargs):
        return None

    def close(self):
        return None


class RecordingHistoryManager(FakeHistoryManager):
    def __init__(self) -> None:
        self.completed_calls: list[dict] = []
        self.step_updates: list[tuple] = []

    def complete_task(self, task_id, result_data=None, error_message=None, status=None):
        self.completed_calls.append(
            {"task_id": task_id, "result_data": result_data, "error_message": error_message, "status": status}
        )

    def update_step_status(self, task_id, step_number, status, result_data=None, error_message=None):
        self.step_updates.append((task_id, step_number, status, error_message))


class _Signal:
    def connect(self, _fn):
        return None


class FakeWatcher:
    def __init__(self, *args, **kwargs):
        self.frame_captured = _Signal()
        self.frame_rate_updated = _Signal()

    def start_watching(self):
        return None

    def stop_watching(self):
        return None


class CountingWatcher(FakeWatcher):
    created = 0

    def __init__(self, *args, **kwargs):
        type(self).created += 1
        super().__init__(*args, **kwargs)


@pytest.mark.asyncio
async def test_orchestrator_worker_execute_success(monkeypatch):
    monkeypatch.setattr(core_module, "MacroPlanner", FakePlanner)
    monkeypatch.setattr(core_module, "TrinityBridge", FakeBridge)
    monkeypatch.setattr(core_module, "HistoryManager", FakeHistoryManager)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "make_provider", lambda name, key: FakeProvider())

    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    worker = OrchestratorWorker("List files", "cli")

    statuses = []
    bus.status_update.connect(lambda msg, level: statuses.append((msg, level)))
    await worker._execute()

    assert any("objective" in message.lower() for message, _level in statuses)
    assert any(level == "success" for _message, level in statuses)


@pytest.mark.asyncio
async def test_orchestrator_worker_cancel_mid_execution(monkeypatch):
    """Cancel fires on the first agent-loop cancel check (start of next iteration)."""
    class SlowProvider:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def call(self, messages, *, json_mode=True):
            self.started.set()
            await self.release.wait()
            # Return a non-done action so the agent loop actually calls bridge
            return json.dumps({
                "rationale": "wait and check",
                "action_type": "cli",
                "module": "cli_runner",
                "parameters": {"command": "echo hi"},
                "done": False,
                "result_summary": None,
            })

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    slow_provider = SlowProvider()
    history = RecordingHistoryManager()
    bus = EventBus()

    monkeypatch.setattr(core_module, "MacroPlanner", FakePlanner)
    monkeypatch.setattr(core_module, "TrinityBridge", FakeBridge)
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "make_provider", lambda name, key: slow_provider)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("Long task", "cli")
    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    run_task = asyncio.create_task(worker._execute())
    await slow_provider.started.wait()
    worker.cancel()
    slow_provider.release.set()
    await run_task

    assert completions[-1]["status"] in ("cancelled", "failure")


@pytest.mark.asyncio
async def test_orchestrator_worker_sanitizes_traceback_status_message(monkeypatch):
    class TracebackProvider:
        """Always returns a CLI action; bridge fails with traceback twice → halted."""
        async def call(self, messages, *, json_mode=True):
            return json.dumps({
                "rationale": "run command",
                "action_type": "cli",
                "module": "cli_runner",
                "parameters": {"command": "fail"},
                "done": False,
                "result_summary": None,
            })

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    class TracebackBridge(FakeBridge):
        async def execute_task(self, task_id, description, domain, **kwargs):
            return _FakeResult(
                task_id=task_id,
                status="failure",
            )

    # Override _extract_result_text in agent_loop to return traceback error
    import orchestrator.agent_loop as agent_loop_module

    def traceback_extract(result):
        if getattr(result, "status", None) != "success":
            return (
                "ERROR: Traceback (most recent call last):\n"
                "  File 'bridge.py', line 99\n"
                "RuntimeError: remote backend blew up"
            )
        return "OK"

    monkeypatch.setattr(agent_loop_module, "_extract_result", traceback_extract)

    bus = EventBus()
    monkeypatch.setattr(core_module, "MacroPlanner", FakePlanner)
    monkeypatch.setattr(core_module, "TrinityBridge", lambda: TracebackBridge())
    monkeypatch.setattr(core_module, "HistoryManager", RecordingHistoryManager)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "make_provider", lambda name, key: TracebackProvider())
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("Run failing task", "cli")

    statuses: list[tuple] = []
    completions: list[dict] = []
    bus.status_update.connect(lambda message, level: statuses.append((message, level)))
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    await worker._execute()

    error_statuses = [msg for msg, level in statuses if level == "error"]
    assert error_statuses
    assert all("Traceback" not in message for message in error_statuses)
    assert completions[-1]["status"] == "failure"
    assert "Traceback" not in str(completions[-1].get("error", ""))


class FakeRunningThread:
    """Thread stub that stays running and never joins."""

    def __init__(self) -> None:
        self._running = True
        self.deleted = False
        self.wait_calls: list[int] = []
        self.quit_called = False
        self.started = _Signal()
        self.finished = _Signal()

    def start(self) -> None:
        return None

    def isRunning(self) -> bool:  # noqa: N802
        return self._running

    def quit(self) -> None:
        self.quit_called = True

    def wait(self, timeout: int) -> bool:
        self.wait_calls.append(timeout)
        return False

    def deleteLater(self) -> None:
        self.deleted = True


class FakeWorkerObject(QObject):
    """QObject-compatible worker stub used for core lifecycle tests."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.deleted = False

    def moveToThread(self, _thread) -> None:  # noqa: N802
        return None

    def run(self) -> None:
        return None

    def cancel(self) -> None:
        return None

    def deleteLater(self) -> None:
        self.deleted = True


class RecordingWorker(FakeWorkerObject):
    def __init__(self, task_description: str, domain: str, **kwargs) -> None:
        super().__init__()
        self.task_description = task_description
        self.domain = domain
        self.kwargs = kwargs


def test_worker_error_does_not_delete_running_thread(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(core_module, "QThread", FakeRunningThread)
    monkeypatch.setattr(core_module, "OrchestratorWorker", lambda *_args, **_kwargs: FakeWorkerObject())

    core = OrchestratorCore()
    core._start_worker("task", "cli")
    assert core.current_thread is not None
    thread = core.current_thread
    worker = core.current_worker
    assert isinstance(thread, FakeRunningThread)
    assert isinstance(worker, FakeWorkerObject)

    core._on_worker_error("backend unavailable")

    assert thread.quit_called is False
    assert thread.deleted is False
    assert worker.deleted is False
    assert core.current_thread is thread
    assert core.current_worker is worker


def test_orchestrator_core_ignores_submit_when_worker_exists(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    core = OrchestratorCore()
    core.current_worker = FakeWorkerObject()
    core._task_running = True
    thread = FakeRunningThread()
    thread._running = False
    core.current_thread = thread

    started: list[tuple] = []
    statuses: list[tuple] = []
    monkeypatch.setattr(core, "_start_worker", lambda description, domain: started.append((description, domain)))
    bus.status_update.connect(lambda message, level: statuses.append((message, level)))

    core.on_task_submitted("second submit", "cli")

    assert started == []
    assert any("task is already running" in message.lower() for message, _level in statuses)


def test_orchestrator_core_blocks_submit_when_startup_guard_set(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    core = OrchestratorCore()
    core.set_startup_guard("Live Gemini blocked: invalid API key.")

    started: list[tuple] = []
    statuses: list[tuple] = []
    monkeypatch.setattr(core, "_start_worker", lambda description, domain: started.append((description, domain)))
    bus.status_update.connect(lambda message, level: statuses.append((message, level)))

    core.on_task_submitted("list files", "cli")

    assert started == []
    assert any("blocked" in message.lower() for message, _level in statuses)


def test_orchestrator_core_tracks_task_running_lifecycle(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(core_module, "QThread", FakeRunningThread)
    monkeypatch.setattr(core_module, "OrchestratorWorker", RecordingWorker)

    core = OrchestratorCore()
    core._start_worker("task", "cli")

    assert core._task_running is True
    assert core.get_submission_block_reason() == "Task is already running."

    assert isinstance(core.current_thread, FakeRunningThread)
    core.current_thread._running = False
    core._on_worker_finished()

    assert core._task_running is False
    assert core.get_submission_block_reason() is None


def test_orchestrator_core_starts_worker_with_saved_runtime_settings(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    class FakeSettingsManager:
        def load(self) -> dict:
            return {
                "gemini_api_key": "test-key",
                "ai_provider": "gemini",
                "openai_api_key": "",
                "default_timeout_seconds": 123,
                "max_retries": 7,
                "default_domain": "CLI",
                "frame_rate_limit": 9,
                "max_frame_count": 44,
                "theme": "dark",
            }

    monkeypatch.setattr(core_module, "SettingsManager", lambda: FakeSettingsManager())
    monkeypatch.setattr(core_module, "QThread", FakeRunningThread)
    monkeypatch.setattr(core_module, "OrchestratorWorker", RecordingWorker)

    core = OrchestratorCore()
    core._start_worker("task", "cli")

    assert isinstance(core.current_worker, RecordingWorker)
    assert core.current_worker.kwargs["timeout_seconds"] == 123
    assert core.current_worker.kwargs["max_retries"] == 7
    assert core.current_worker.kwargs["frame_rate_limit"] == 9
    assert core.current_worker.kwargs["max_frame_count"] == 44


def test_worker_defers_screenshot_watcher_creation_until_execute(monkeypatch):
    monkeypatch.setattr(core_module, "ScreenshotWatcher", CountingWatcher)
    bus = EventBus()
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    CountingWatcher.created = 0
    worker = OrchestratorWorker("List files", "cli")

    assert CountingWatcher.created == 0
    assert worker.screenshot_watcher is None
