"""Contract tests for Trinity bridge and orchestrator worker behavior."""
from __future__ import annotations

import json

import pytest


def _is_reflection_call(messages: list[dict]) -> bool:
    system = messages[0].get("content", "") if messages else ""
    return "achieved" in system and "critique" in system

import orchestrator.orchestrator_core as core_module
from orchestrator.event_bus import EventBus
from orchestrator.macro_planner import ExecutionPlan
from orchestrator.orchestrator_core import OrchestratorWorker
from orchestrator.trinity_bridge import TrinityBridge


class FakeTaskResult:
    def __init__(self, task_id: str, status: str = "success", error: str | None = None) -> None:
        self.task_id = task_id
        self.status = status
        self.output = "ok" if status == "success" else None
        self.error = error

    def model_dump(self) -> dict:
        return {"task_id": self.task_id, "status": self.status, "error": self.error}


class FakeExecutor:
    def __init__(self) -> None:
        self.initialized = False
        self.last_task = None

    async def initialize(self) -> None:
        self.initialized = True

    async def execute(self, task):
        self.last_task = task
        return FakeTaskResult(task_id=task.task_id, status="success")

    async def shutdown(self) -> None:
        self.initialized = False


class FakeHistoryManager:
    def create_task(self, *args, **kwargs): return None
    def start_task(self, *args, **kwargs): return None
    def complete_task(self, *args, **kwargs): return None
    def add_step(self, *args, **kwargs): return None
    def update_step_status(self, *args, **kwargs): return None
    def close(self): return None


class FakeWatcher:
    class _Signal:
        def connect(self, _fn): return None

    def __init__(self, *args, **kwargs):
        self.frame_captured = self._Signal()
        self.frame_rate_updated = self._Signal()

    def start_watching(self): return None
    def stop_watching(self): return None


class SingleStepPlanner:
    def __init__(self, provider=None, registry=None) -> None: pass

    async def generate_plan(self, _description: str, domain: str) -> ExecutionPlan:
        return ExecutionPlan(
            description="demo",
            domain=domain,
            steps=["step a"],
            estimated_duration=5,
            confidence=0.9,
        )


class ImmediateDoneProvider:
    """Provider that immediately marks objectives as done."""

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

    async def probe(self) -> None: pass

    @property
    def provider_name(self) -> str:
        return "fake"


# ── TrinityBridge tests (test bridge directly, unaffected by new architecture) ──

@pytest.mark.asyncio
async def test_trinity_bridge_forwards_contract_fields():
    bridge = TrinityBridge()
    fake = FakeExecutor()
    bridge.executor = fake
    await bridge.initialize()

    cancel_event = object()
    await bridge.execute_task(
        task_id="test-bridge-contract",
        description="List files",
        domain="cli",
        timeout=600,
        max_retries=3,
        cancel_event=cancel_event,
    )

    assert fake.last_task is not None
    assert fake.last_task.timeout == 600
    assert fake.last_task.max_retries == 3
    assert fake.last_task.cancel_event is cancel_event


# ── Worker contract tests (AgentLoop-based) ──────────────────────────────────

@pytest.mark.asyncio
async def test_worker_completes_successfully_when_objectives_done(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr(core_module, "MacroPlanner", SingleStepPlanner)
    monkeypatch.setattr(core_module, "TrinityBridge", lambda: _NoOpBridge())
    monkeypatch.setattr(core_module, "HistoryManager", FakeHistoryManager)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "make_provider", lambda name, key: ImmediateDoneProvider())
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("List files", "cli")
    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))
    await worker._execute()

    assert completions[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_worker_emits_failure_when_agent_loop_halts(monkeypatch):
    """When the agent loop halts (e.g. max iterations), execution emits failure."""
    call_count = 0

    class LoopingProvider:
        async def call(self, messages, *, json_mode=True):
            nonlocal call_count
            call_count += 1
            return json.dumps({
                "rationale": "keep going",
                "action_type": "cli",
                "module": "cli_runner",
                "parameters": {"command": "echo test"},
                "done": False,
                "result_summary": None,
            })

        async def probe(self): pass

        @property
        def provider_name(self): return "fake"

    bus = EventBus()
    monkeypatch.setattr(core_module, "MacroPlanner", SingleStepPlanner)
    monkeypatch.setattr(core_module, "TrinityBridge", lambda: _NoOpBridge())
    monkeypatch.setattr(core_module, "HistoryManager", FakeHistoryManager)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "make_provider", lambda name, key: LoopingProvider())
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    # Patch MAX_ITERATIONS to 2 so the test completes fast
    import orchestrator.agent_loop as agent_loop_module
    monkeypatch.setattr(agent_loop_module, "MAX_ITERATIONS", 2)

    worker = OrchestratorWorker("Never-ending task", "cli")
    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))
    await worker._execute()

    assert completions[-1]["status"] == "failure"


@pytest.mark.asyncio
async def test_worker_can_run_again_after_failure(monkeypatch):
    """Two sequential workers — first fails, second succeeds."""
    bus1 = EventBus()
    bus2 = EventBus()

    call_count = [0]

    class ToggleProvider:
        async def call(self, messages, *, json_mode=True):
            call_count[0] += 1
            if _is_reflection_call(messages):
                return json.dumps({"achieved": True, "confidence": 0.95, "critique": None})
            return json.dumps({
                "rationale": "done",
                "action_type": "done",
                "module": None,
                "parameters": {},
                "done": True,
                "result_summary": "ok",
            })

        async def probe(self): pass

        @property
        def provider_name(self): return "fake"

    class FailingPlanner:
        def __init__(self, provider=None, registry=None): pass

        async def generate_plan(self, _desc, _domain):
            raise RuntimeError("planner failed")

    class SuccessPlanner:
        def __init__(self, provider=None, registry=None): pass

        async def generate_plan(self, _desc, _domain) -> ExecutionPlan:
            return ExecutionPlan(description="ok", domain="cli", steps=["obj1"], estimated_duration=5, confidence=0.9)

    monkeypatch.setattr(core_module, "TrinityBridge", lambda: _NoOpBridge())
    monkeypatch.setattr(core_module, "HistoryManager", FakeHistoryManager)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "make_provider", lambda name, key: ToggleProvider())

    monkeypatch.setattr(core_module, "MacroPlanner", FailingPlanner)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus1)
    first_worker = OrchestratorWorker("Failing task", "cli")
    first_completions: list[dict] = []
    bus1.execution_complete.connect(lambda p: first_completions.append(p))
    await first_worker._execute()

    monkeypatch.setattr(core_module, "MacroPlanner", SuccessPlanner)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus2)
    second_worker = OrchestratorWorker("Success task", "cli")
    second_completions: list[dict] = []
    bus2.execution_complete.connect(lambda p: second_completions.append(p))
    await second_worker._execute()

    assert first_completions[-1]["status"] == "failure"
    assert second_completions[-1]["status"] == "success"


class _NoOpBridge:
    async def initialize(self): return None
    async def execute_task(self, task_id, description, domain, **kwargs):
        return FakeTaskResult(task_id=task_id, status="success")
    async def shutdown(self): return None
