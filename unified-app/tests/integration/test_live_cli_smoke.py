"""Optional real-Gemini CLI smoke test for the demo path."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import orchestrator.orchestrator_core as core_module
import pytest
from dotenv import load_dotenv
from orchestrator.database import TaskStatus
from orchestrator.event_bus import EventBus
from orchestrator.orchestrator_core import OrchestratorWorker


LIVE_SMOKE_ENABLED = os.getenv("LIVE_GEMINI_SMOKE", "0") == "1"
SMOKE_TIMEOUT_SECONDS = 60
SMOKE_OBJECTIVE = "list files in current directory"

pytestmark = [pytest.mark.integration, pytest.mark.live, pytest.mark.asyncio]


class _Signal:
    """Minimal Qt-free signal stub."""

    def connect(self, _fn: Any) -> None:  # noqa: ANN001
        return None


class FakeWatcher:
    """No-op screenshot watcher for integration testing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.frame_captured = _Signal()
        self.frame_rate_updated = _Signal()

    def start_watching(self) -> None:
        return None

    def stop_watching(self) -> None:
        return None


class RecordingHistoryManager:
    """Record terminal task state without touching the real DB."""

    def __init__(self) -> None:
        self.completed_calls: list[dict[str, Any]] = []

    def create_task(self, *args: Any, **kwargs: Any) -> None:
        return None

    def start_task(self, *args: Any, **kwargs: Any) -> None:
        return None

    def add_step(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_step_status(self, *args: Any, **kwargs: Any) -> None:
        return None

    def complete_task(
        self,
        task_id: Any,
        result_data: Any = None,
        error_message: Any = None,
        status: Any = None,
    ) -> None:
        derived = (
            status
            if status is not None
            else (TaskStatus.COMPLETED if not error_message else TaskStatus.FAILED)
        )
        self.completed_calls.append(
            {
                "task_id": task_id,
                "result_data": result_data,
                "error_message": error_message,
                "status": derived,
            }
        )

    def close(self) -> None:
        return None


class RecordingBridge:
    """Capture bridge task calls for worker assertions."""

    instances: list["RecordingBridge"] = []

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.__class__.instances.append(self)

    async def initialize(self) -> None:
        return None

    async def execute_task(
        self,
        task_id: str,
        description: str,
        domain: str,
        context: dict[str, Any] | None = None,
        expected_outcome: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        cancel_event: Any = None,
    ) -> Any:
        self.calls.append(
            {
                "task_id": task_id,
                "description": description,
                "domain": domain,
                "context": context,
                "expected_outcome": expected_outcome,
            }
        )
        return type("Result", (), {"status": "success", "model_dump": lambda self: {"status": "success"}})()

    async def shutdown(self) -> None:
        return None


async def test_live_cli_smoke_reaches_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run one bounded live CLI task or skip when live smoke is not enabled."""
    if not LIVE_SMOKE_ENABLED:
        pytest.skip("set LIVE_GEMINI_SMOKE=1 to run the real Gemini smoke test")

    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path, override=False)
    monkeypatch.delenv("GEMINI_MOCK", raising=False)

    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("set GEMINI_API_KEY or unified-app/.env before running live smoke")

    history = RecordingHistoryManager()
    bus = EventBus()
    status_messages: list[tuple[str, str]] = []
    bus.status_update.connect(lambda msg, level: status_messages.append((msg, level)))
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker(SMOKE_OBJECTIVE, "cli")
    await asyncio.wait_for(worker._execute(), timeout=SMOKE_TIMEOUT_SECONDS)

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED
    assert final["result_data"] == {"status": "success", "category": "success"}
    assert any(
        level == "success" and "Execution completed" in msg
        for msg, level in status_messages
    ), "No successful completion status message was emitted"


async def test_worker_forwards_expected_outcome_to_trinity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AgentLoop must route actions through TrinityBridge during task execution."""
    import json

    history = RecordingHistoryManager()
    bus = EventBus()
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(core_module, "TrinityBridge", RecordingBridge)

    _responses = [
        # AgentLoop turn 1: take a CLI action
        json.dumps({
            "rationale": "run dir to list files",
            "action_type": "cli",
            "module": "cli_runner",
            "parameters": {"command": "dir"},
            "done": False,
            "result_summary": None,
        }),
        # AgentLoop turn 2: done
        json.dumps({
            "rationale": "listing complete",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Files listed successfully",
        }),
    ]

    class _SeqProvider:
        provider_name = "stub"
        _idx = 0

        async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
            resp = _responses[min(self._idx, len(_responses) - 1)]
            self._idx += 1
            return resp

        async def probe(self) -> None:
            pass

    monkeypatch.setattr(core_module, "make_provider", lambda *_a, **_kw: _SeqProvider())

    class _StubStep:
        description = "list files in current directory"
        domain = "cli"
        expected_outcome = "Files listed successfully"

    class StubPlan:
        steps = ["list files in current directory"]
        estimated_duration = "0.5s"
        confidence = 0.6
        structured_steps = [_StubStep()]

    class StubPlanner:
        async def generate_plan(self, task_description: str, domain: str) -> StubPlan:
            return StubPlan()

    monkeypatch.setattr(core_module, "MacroPlanner", lambda _provider, **_kw: StubPlanner())
    RecordingBridge.instances.clear()

    worker = OrchestratorWorker("list files in current directory", "cli")
    await worker._execute()

    assert RecordingBridge.instances
    calls = RecordingBridge.instances[-1].calls
    assert calls, "AgentLoop never called TrinityBridge.execute_task()"
    assert calls[0]["domain"] == "cli"
