"""Focused tests for the extracted orchestration execution runner."""
from __future__ import annotations

import json

import pytest

from orchestrator.event_bus import EventBus
from orchestrator.database import TaskStatus
from orchestrator.macro_planner import ExecutionPlan
from trinity_core.models import ExecutionLog, TaskResult


def _is_reflection_call(messages: list[dict]) -> bool:
    """Detect if the provider is being called for reflection vs action."""
    system = messages[0].get("content", "") if messages else ""
    return "achieved" in system and "critique" in system


def _is_replan_call(messages: list[dict]) -> bool:
    system = messages[0].get("content", "") if messages else ""
    return "revised_objectives" in system


class FakeProvider:
    """LLMProvider stub that returns the right JSON for action, reflection, or replan calls."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        if _is_reflection_call(messages):
            return json.dumps({"achieved": True, "confidence": 0.95, "critique": None})
        if _is_replan_call(messages):
            return json.dumps({"revised_objectives": [], "rationale": "nothing left"})
        return json.dumps({
            "rationale": "objective achieved",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "task complete",
        })

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"

    async def close(self) -> None:
        pass


class ActionThenDoneProvider(FakeProvider):
    """Execute one action, then finish, while reflection continues to succeed."""

    def __init__(self) -> None:
        self._action_calls = 0

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        if _is_reflection_call(messages):
            return json.dumps({"achieved": True, "confidence": 0.95, "critique": None})
        if _is_replan_call(messages):
            return json.dumps({"revised_objectives": [], "rationale": "nothing left"})
        self._action_calls += 1
        if self._action_calls == 1:
            return json.dumps({
                "rationale": "open the page first",
                "action_type": "browse",
                "module": "web_browser",
                "parameters": {"action": "navigate", "url": "https://example.com"},
                "done": False,
            })
        return json.dumps({
            "rationale": "objective achieved",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "task complete",
        })


class FakePlanner:
    """Return a deterministic one-objective plan."""

    def __init__(self, provider=None) -> None:
        pass

    async def generate_plan(self, _description: str, domain: str) -> ExecutionPlan:
        return ExecutionPlan(
            description="runner demo",
            domain=domain,
            steps=["achieve the objective"],
            estimated_duration=5,
            confidence=0.9,
        )

    async def replan(self, original_task, completed, failed, remaining) -> list[str]:
        return remaining


class RecordingBridge:
    """Record bridge calls and return success."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def execute_task(self, task_id, description, domain, **kwargs):
        self.calls.append({"task_id": task_id, "description": description, "domain": domain, **kwargs})
        return _FakeResult(task_id=task_id)

    async def shutdown(self) -> None:
        self.shutdown_called = True


class _FakeResult:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.status = "success"
        self.output = "ok"

    def model_dump(self) -> dict:
        return {"task_id": self.task_id, "status": self.status}


class StructuredBridge(RecordingBridge):
    """Return a structured Trinity result so runner persistence can preserve it."""

    async def execute_task(self, task_id, description, domain, **kwargs):
        self.calls.append({"task_id": task_id, "description": description, "domain": domain, **kwargs})
        return TaskResult(
            task_id=task_id,
            status="success",
            category="success",
            error=None,
            execution_log=[
                ExecutionLog(
                    step=1,
                    action="open browser",
                    result="success",
                    details="Opened the page successfully.",
                    timestamp="2026-03-24T08:00:00",
                )
            ],
            artifacts=["_runtime/output/front.png"],
            metadata={
                "raw_result": {"status": "success", "successful_actions": 1},
                "output": "Opened https://example.com",
            },
        )


class RecordingHistoryManager:
    """Capture runner persistence side effects."""

    def __init__(self) -> None:
        self.created_tasks: list[dict] = []
        self.started_tasks: list[str] = []
        self.completed_tasks: list[dict] = []
        self.added_steps: list[tuple] = []
        self.step_updates: list[tuple] = []
        self.closed = False

    def create_task(self, **kwargs) -> None:
        self.created_tasks.append(kwargs)

    def start_task(self, task_id: str) -> None:
        self.started_tasks.append(task_id)

    def complete_task(self, task_id, result_data=None, error_message=None, status=None) -> None:
        self.completed_tasks.append(
            {"task_id": task_id, "result_data": result_data, "error_message": error_message, "status": status}
        )

    def add_step(self, task_id: str, step_number: int, description: str) -> None:
        self.added_steps.append((task_id, step_number, description))

    def update_step_status(self, task_id, step_number, status, result_data=None, error_message=None) -> None:
        self.step_updates.append((task_id, step_number, status, result_data, error_message))

    def close(self) -> None:
        self.closed = True


class FakeWatcher:
    """Minimal watcher stub for runner lifecycle checks."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start_watching(self) -> None:
        self.started = True

    def stop_watching(self) -> None:
        self.stopped = True


class FakeErrorHandler:
    """No-op error handler for success-path tests."""

    def handle(self, exc: Exception, context: str, category: str | None = None) -> dict:
        return {"message": "handled", "user_message": "handled", "category": category or "backend_error"}

    def build_user_message(self, message: str, category: str | None = None) -> str:
        return message


class AlwaysAchievedProvider:
    """Reflection provider that incorrectly says every attempt succeeded."""

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        if _is_replan_call(messages):
            return json.dumps({"revised_objectives": [], "rationale": "nothing left"})
        return json.dumps({"achieved": True, "confidence": 0.99, "critique": None})

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"

    async def close(self) -> None:
        pass


class DeletedBus:
    """Simulate a deleted Qt event bus owner."""

    def __getattr__(self, _name: str):
        raise RuntimeError("wrapped C/C++ object of type EventBus has been deleted")

    def emit_status(self, _message: str, _level: str = "info") -> None:
        raise RuntimeError("wrapped C/C++ object of type EventBus has been deleted")


def _make_runner(bus, bridge, history, watcher, **kwargs):
    from orchestrator.execution_runner import TaskExecutionRunner

    return TaskExecutionRunner(
        run_id=kwargs.pop("run_id", "run_test"),
        task_description=kwargs.pop("task_description", "List files"),
        domain=kwargs.pop("domain", "cli"),
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=FakePlanner(),
        provider=FakeProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_execution_runner_executes_success_flow_and_cleans_up():
    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = _make_runner(bus, bridge, history, watcher)

    completions: list[dict] = []
    statuses: list[tuple] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))
    bus.status_update.connect(lambda message, level: statuses.append((message, level)))

    await runner.execute()

    assert bridge.initialized is True
    assert bridge.shutdown_called is True
    assert watcher.started is True
    assert watcher.stopped is True
    assert history.closed is True
    assert history.created_tasks[0]["task_id"] == "run_test"
    assert history.started_tasks == ["run_test"]
    assert history.completed_tasks[-1]["result_data"]["status"] == "success"
    assert completions[-1]["status"] == "success"
    assert any("objective" in message.lower() for message, _level in statuses)
    assert any(
        level == "success" and "Execution completed successfully" in message
        for message, level in statuses
    )


@pytest.mark.asyncio
async def test_execution_runner_preserves_structured_step_payload_from_bridge():
    bus = EventBus()
    bridge = StructuredBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    from orchestrator.execution_runner import TaskExecutionRunner

    runner = TaskExecutionRunner(
        run_id="run_structured",
        task_description="Open example.com",
        domain="web",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=FakePlanner(),
        provider=ActionThenDoneProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
    )

    step_payloads: list[dict] = []
    bus.step_completed.connect(lambda _index, payload: step_payloads.append(payload))

    await runner.execute()

    assert step_payloads, "No step completion payload was emitted"
    payload = step_payloads[-1]
    assert payload["status"] == "success"
    assert payload["artifacts"] == ["_runtime/output/front.png"]
    assert payload["execution_log"][0]["details"] == "Opened the page successfully."
    assert payload["metadata"]["raw_result"]["successful_actions"] == 1
    assert history.step_updates[-1][3]["artifacts"] == ["_runtime/output/front.png"]
    assert history.step_updates[-1][3]["metadata"]["raw_result"]["successful_actions"] == 1


@pytest.mark.asyncio
async def test_execution_runner_tolerates_deleted_event_bus_owner():
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = _make_runner(DeletedBus(), bridge, history, watcher, run_id="run_deleted_bus")

    await runner.execute()

    assert bridge.shutdown_called is True
    assert history.closed is True


@pytest.mark.asyncio
async def test_execution_runner_handles_plan_failure_gracefully():
    class FailingPlanner:
        def __init__(self, provider=None):
            pass

        async def generate_plan(self, _desc, _domain):
            raise RuntimeError("planner is down")

    from orchestrator.execution_runner import TaskExecutionRunner

    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = TaskExecutionRunner(
        run_id="run_plan_fail",
        task_description="fail task",
        domain="cli",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=FailingPlanner(),
        provider=FakeProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
    )

    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))
    await runner.execute()

    assert bridge.shutdown_called is True
    assert history.closed is True
    assert completions[-1]["status"] == "failure"


@pytest.mark.asyncio
async def test_execution_runner_cancel_before_first_objective_exits_cleanly():
    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()

    from orchestrator.execution_runner import TaskExecutionRunner

    runner = TaskExecutionRunner(
        run_id="run_cancel",
        task_description="cancel task",
        domain="cli",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=FakePlanner(),
        provider=FakeProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: True,
        cancel_event=object(),
    )

    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))
    await runner.execute()

    assert bridge.shutdown_called is True
    assert history.closed is True
    assert completions[-1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_execution_runner_does_not_count_failure_reporting_step_as_partial(monkeypatch):
    class FailureThenReportPlanner:
        async def generate_plan(self, _description: str, domain: str) -> ExecutionPlan:
            return ExecutionPlan(
                description="missing app",
                domain=domain,
                steps=["Open the application 'MissingApp' and tell me its version number"],
                estimated_duration=5,
                confidence=0.9,
            )

        async def replan(self, original_task, completed, failed, remaining, constraints=None) -> list[str]:
            return ["Report that the application could not be found"]

    class ReflectionProvider:
        async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
            if _is_reflection_call(messages):
                objective = messages[1]["content"]
                achieved = "Report that the application could not be found" in objective
                return json.dumps(
                    {
                        "achieved": achieved,
                        "confidence": 0.95,
                        "critique": None if achieved else "The app could not be opened.",
                    }
                )
            return json.dumps({"revised_objectives": [], "rationale": "unused"})

    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.last_step_payload = None

        async def act(self, objective, obj_index, context=None, adapt_hint="") -> str:
            if "Report that the application could not be found" in objective:
                self.last_step_payload = {
                    "status": "success",
                    "output": "Reported that the application could not be found.",
                    "artifacts": [],
                    "execution_log": [],
                    "metadata": {},
                }
                return "Reported that the application could not be found."
            self.last_step_payload = None
            return "ERROR: Application not found"

    from orchestrator import execution_runner as runner_module
    from orchestrator.execution_runner import TaskExecutionRunner

    monkeypatch.setattr(runner_module, "AgentLoop", FakeAgentLoop)

    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = TaskExecutionRunner(
        run_id="run_failure_report",
        task_description="Open MissingApp and tell me its version",
        domain="desktop",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=FailureThenReportPlanner(),
        provider=ReflectionProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
    )

    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    await runner.execute()

    assert completions[-1]["status"] == "failure"
    assert history.completed_tasks[-1]["result_data"]["status"] == "failure"


@pytest.mark.asyncio
async def test_execution_runner_preserves_failure_status_for_app_not_found(monkeypatch):
    class SingleFailurePlanner:
        async def generate_plan(self, _description: str, domain: str) -> ExecutionPlan:
            return ExecutionPlan(
                description="missing app",
                domain=domain,
                steps=["Open an application called 'NonExistentApp_XYZ123456' and tell me its version number"],
                estimated_duration=5,
                confidence=0.9,
            )

        async def replan(self, original_task, completed, failed, remaining, constraints=None) -> list[str]:
            return remaining

    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.last_step_payload = None

        async def act(self, objective, obj_index, context=None, adapt_hint="") -> str:
            self.last_step_payload = {
                "status": "failure",
                "output": (
                    "ERROR: The application 'NonExistentApp_XYZ123456' could not be found. "
                    "Therefore, its version number cannot be determined."
                ),
                "artifacts": [],
                "execution_log": [],
                "metadata": {
                    "raw_result": {
                        "status": "failure",
                        "error": (
                            "Could not find the NonExistentApp_XYZ123456 window. "
                            "Please make sure the application is installed."
                        ),
                    }
                },
            }
            return "Mock task completed successfully"

    from orchestrator import execution_runner as runner_module
    from orchestrator.execution_runner import TaskExecutionRunner

    monkeypatch.setattr(runner_module, "AgentLoop", FakeAgentLoop)

    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = TaskExecutionRunner(
        run_id="run_app_not_found",
        task_description="Open an application called 'NonExistentApp_XYZ123456' and tell me its version number",
        domain="desktop",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=SingleFailurePlanner(),
        provider=AlwaysAchievedProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
    )

    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    await runner.execute()

    assert completions[-1]["status"] == "failure"
    assert history.completed_tasks[-1]["result_data"]["status"] == "failure"
    assert history.step_updates[-1][2] == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_execution_runner_preserves_partial_status_when_later_step_fails(monkeypatch):
    class MixedPlanner:
        async def generate_plan(self, _description: str, domain: str) -> ExecutionPlan:
            return ExecutionPlan(
                description="mixed task",
                domain=domain,
                steps=[
                    "First run 'python --version' in the CLI to get the Python version",
                    "Then open an application called 'InvalidSoftware_ABCDEF' that does not exist",
                ],
                estimated_duration=10,
                confidence=0.9,
            )

        async def replan(self, original_task, completed, failed, remaining, constraints=None) -> list[str]:
            return remaining

    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.last_step_payload = None

        async def act(self, objective, obj_index, context=None, adapt_hint="") -> str:
            if "python --version" in objective.lower():
                self.last_step_payload = {
                    "status": "success",
                    "output": "Python 3.12.1",
                    "artifacts": [],
                    "execution_log": [],
                    "metadata": {},
                }
                return "Python 3.12.1"

            self.last_step_payload = {
                "status": "failure",
                "output": (
                    "ERROR: The application 'InvalidSoftware_ABCDEF' could not be found. "
                    "Therefore, its version number cannot be determined."
                ),
                "artifacts": [],
                "execution_log": [],
                "metadata": {
                    "raw_result": {
                        "status": "failure",
                        "error": "Could not find the InvalidSoftware_ABCDEF window.",
                    }
                },
            }
            return "Mock task completed successfully"

    from orchestrator import execution_runner as runner_module
    from orchestrator.execution_runner import TaskExecutionRunner

    monkeypatch.setattr(runner_module, "AgentLoop", FakeAgentLoop)

    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = TaskExecutionRunner(
        run_id="run_mixed_partial",
        task_description="First run 'python --version' in the CLI to get the Python version, then open an application called 'InvalidSoftware_ABCDEF' that does not exist",
        domain="mixed",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=MixedPlanner(),
        provider=AlwaysAchievedProvider(),
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
    )

    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    await runner.execute()

    assert completions[-1]["status"] == "partial"
    assert history.completed_tasks[-1]["result_data"]["status"] == "partial"
    assert history.step_updates[-1][2] == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_execution_runner_emits_task_result_ready_on_success():
    """task_result_ready signal must fire once with a non-empty chat summary on success."""
    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = _make_runner(bus, bridge, history, watcher, task_description="List files")

    result_msgs: list[str] = []
    bus.task_result_ready.connect(lambda msg: result_msgs.append(msg))

    await runner.execute()

    assert len(result_msgs) == 1, f"Expected exactly one task_result_ready emission; got {result_msgs}"
    assert result_msgs[0], "task_result_ready payload must not be empty"
    # Success path: message should reference the task
    assert "List files" in result_msgs[0] or "completed" in result_msgs[0].lower()


@pytest.mark.asyncio
async def test_execution_runner_emits_task_result_ready_on_failure():
    """task_result_ready signal fires even when the task fails."""

    class FailingBridge(RecordingBridge):
        async def execute_task(self, task_id, description, domain, **kwargs):
            self.calls.append({"task_id": task_id})
            result = _FakeResult(task_id=task_id)
            result.status = "failure"
            result.output = "ERROR: could not complete"
            return result

    bus = EventBus()
    bridge = FailingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    runner = _make_runner(bus, bridge, history, watcher, task_description="Open MissingApp")

    result_msgs: list[str] = []
    bus.task_result_ready.connect(lambda msg: result_msgs.append(msg))

    await runner.execute()

    assert len(result_msgs) == 1, f"Expected exactly one task_result_ready emission; got {result_msgs}"
    assert result_msgs[0], "task_result_ready payload must not be empty"


@pytest.mark.asyncio
async def test_execution_runner_closes_provider_before_loop_shutdown():
    class ClosingProvider(FakeProvider):
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    from orchestrator.execution_runner import TaskExecutionRunner

    bus = EventBus()
    bridge = RecordingBridge()
    history = RecordingHistoryManager()
    watcher = FakeWatcher()
    provider = ClosingProvider()
    runner = TaskExecutionRunner(
        run_id="run_provider_close",
        task_description="List files",
        domain="cli",
        event_bus=bus,
        history_manager=history,
        error_handler=FakeErrorHandler(),
        planner=FakePlanner(),
        provider=provider,
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=object(),
    )

    await runner.execute()

    assert provider.closed is True
