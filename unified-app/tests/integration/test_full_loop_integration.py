"""Integration tests for the direct Desktop -> Core handoff path."""
from __future__ import annotations

from typing import Any

import orchestrator.orchestrator_core as core_module
import pytest
from orchestrator.database import TaskStatus
from orchestrator.event_bus import EventBus
from orchestrator.orchestrator_core import UnifiedAppObjectiveRunner


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class RecordingHistoryManager:
    def __init__(self) -> None:
        self.completed_calls: list[dict[str, Any]] = []
        self.step_updates: list[dict[str, Any]] = []

    def create_task(self, *args: Any, **kwargs: Any) -> None:
        return None

    def start_task(self, *args: Any, **kwargs: Any) -> None:
        return None

    def add_sub_objective(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_step_status(
        self,
        task_id: Any,
        step_number: Any,
        status: Any,
        result_data: Any = None,
        error_message: Any = None,
        flight_report_path: Any = None,
    ) -> None:
        self.step_updates.append(
            {
                "task_id": task_id,
                "step_number": step_number,
                "status": status,
                "result_data": result_data,
                "error_message": error_message,
                "flight_report_path": flight_report_path,
            }
        )

    def complete_task(
        self,
        task_id: Any,
        result_data: Any = None,
        error_message: Any = None,
        status: Any = None,
    ) -> None:
        self.completed_calls.append(
            {
                "task_id": task_id,
                "result_data": result_data,
                "error_message": error_message,
                "status": status,
            }
        )


class _Result:
    def __init__(self, *, status: str = "success", category: str = "success", output: str = "done") -> None:
        self.status = status
        self.category = category
        self.metadata = {"output": output}
        self.error = None if status == "success" else output

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "category": self.category,
            "metadata": dict(self.metadata),
            "error": self.error,
        }


class RecordingBridge:
    instances: list["RecordingBridge"] = []

    def __init__(self) -> None:
        self.execute_calls: list[dict[str, Any]] = []
        RecordingBridge.instances.append(self)

    async def initialize(self) -> None:
        return None

    async def execute_task(self, **kwargs: Any) -> _Result:
        self.execute_calls.append(kwargs)
        return _Result(output=f"executed via {kwargs['target_server']}")

    async def shutdown(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_bridge_instances() -> None:
    RecordingBridge.instances.clear()


async def test_worker_hands_finalized_objective_to_core_with_selected_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = RecordingHistoryManager()
    bus = EventBus()
    completions: list[dict[str, Any]] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(core_module, "TrinityBridge", RecordingBridge)

    worker = UnifiedAppObjectiveRunner(
        "List files in the current directory",
        "cli",
        approved_plan=["Inspect the current directory", "Summarize the result"],
    )
    await worker._execute()

    bridge = RecordingBridge.instances[-1]
    assert bridge.execute_calls, "Desktop never handed the finalized objective to Core"
    handoff = bridge.execute_calls[-1]
    assert handoff["domain"] == "cli"
    assert handoff["target_server"] == "cli_mcp"
    assert handoff["sub_objectives"] == ["Inspect the current directory", "Summarize the result"]
    assert "expected_outcome" not in handoff

    assert history.completed_calls[-1]["status"] == TaskStatus.COMPLETED
    assert completions[-1]["status"] == "success"
    assert completions[-1]["target_server"] == "cli_mcp"


async def test_worker_reduces_mixed_request_to_one_selected_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = RecordingHistoryManager()
    bus = EventBus()

    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(core_module, "TrinityBridge", RecordingBridge)

    worker = UnifiedAppObjectiveRunner("Open GitHub and inspect the issue page", "mixed")
    await worker._execute()

    bridge = RecordingBridge.instances[-1]
    handoff = bridge.execute_calls[-1]
    assert handoff["domain"] == "web"
    assert handoff["target_server"] == "browser_mcp"
    assert history.completed_calls[-1]["status"] == TaskStatus.COMPLETED
