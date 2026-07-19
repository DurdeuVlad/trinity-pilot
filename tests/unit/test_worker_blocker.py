"""Tests for WorkerBlocker and engine integration (Stories 1 and 9)."""
from __future__ import annotations

import asyncio

import pytest

from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.worker_result import WorkerResult


# ---------------------------------------------------------------------------
# Story 1: WorkerBlocker basics
# ---------------------------------------------------------------------------

def test_worker_blocker_is_subclass_of_worker_error():
    assert issubclass(WorkerBlocker, WorkerError)


def test_worker_blocker_carries_result():
    result = WorkerResult(status="partial_blocker")
    exc = WorkerBlocker("file not found", result)
    assert exc.result.status == "partial_blocker"
    assert str(exc) == "file not found"


# ---------------------------------------------------------------------------
# Story 9: Engine integration tests
# ---------------------------------------------------------------------------

def _make_settings():
    from trinity_pilot.config import Settings
    return Settings(gemini_api_key="fake-key")


def _spec():
    from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
    return ObjectiveSpec(
        objective_id="obj-blocker",
        goal="do something",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["stdout contains hello"],
        evidence_bundle=["stdout"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


class _BlockerWorker:
    """Worker that always raises WorkerBlocker."""

    async def execute(self, spec):
        result = WorkerResult(status="partial_blocker", summary="file not found")
        raise WorkerBlocker("file not found", result)


class _SuccessOnSecondWorker:
    """Worker that raises WorkerBlocker on attempt 1, then succeeds on attempt 2."""

    def __init__(self):
        self._attempt = 0

    async def execute(self, spec):
        self._attempt += 1
        if self._attempt == 1:
            result = WorkerResult(status="partial_blocker")
            raise WorkerBlocker("blocked on first attempt", result)
        return {"stdout": "hello", "exit_code": 0}


class _Reviewer:
    def __init__(self, provider):
        pass

    async def review(self, spec, evidence):
        from trinity_pilot.core.types import ReviewResult
        return ReviewResult(passed=True, notes="ok")


def _make_ask_user_analyser():
    """Analyser mock that returns ask_user."""
    from trinity_pilot.orchestrator.analyser import OrchestratorAnalyser, SteerDecision

    class _MockAnalyser:
        async def analyse(self, spec, retry_context, blocker_reason):
            return SteerDecision(action="ask_user", guidance="", question="What file?")

    return _MockAnalyser()


def _make_auto_steer_analyser():
    """Analyser mock that returns auto_steer."""
    from trinity_pilot.orchestrator.analyser import OrchestratorAnalyser, SteerDecision

    class _MockAnalyser:
        async def analyse(self, spec, retry_context, blocker_reason):
            return SteerDecision(action="auto_steer", guidance="try with elevated permissions", question="")

    return _MockAnalyser()


@pytest.mark.asyncio
async def test_engine_catches_blocker_before_worker_error(tmp_path, monkeypatch):
    """WorkerBlocker is caught before WorkerError; STUCK state and StuckSignal emitted."""
    import trinity_pilot.orchestrator.engine as engine_mod
    from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator
    from trinity_pilot.orchestrator.signals import StuckSignal
    from trinity_pilot.orchestrator.fsm import ObjectiveState
    from trinity_pilot.memory.store import ObjectiveStateStore

    analyser = _make_ask_user_analyser()

    monkeypatch.setattr(engine_mod, "GeminiProvider", lambda **kwargs: object())
    monkeypatch.setattr(engine_mod, "ObjectiveReviewer", _Reviewer)
    async def dispatch(self, domain, spec):
        return await _BlockerWorker().execute(spec)

    monkeypatch.setattr(engine_mod.MCPClientPool, "dispatch", dispatch)
    monkeypatch.setattr(engine_mod, "OrchestratorAnalyser", lambda llm: analyser)

    db_path = tmp_path / "state.db"
    orchestrator = AsyncTaskOrchestrator(
        _make_settings(),
        db_path=str(db_path),
    )

    spec = _spec()
    spec.max_attempts = 1
    result = await orchestrator.run("do something", task_id="task-blocker", objectives=[spec])

    assert result["status"] == "failed"
    assert result.get("results", {}).get("obj-blocker", {}).get("failure_reason") == "blocker_needs_user_input"

    row = ObjectiveStateStore(db_path).get("task-blocker", "obj-blocker")
    assert row["state"] == ObjectiveState.STUCK.value

    # Check StuckSignal was emitted
    signals = []
    while not orchestrator.signals.empty():
        signals.append(orchestrator.signals.get_nowait())
    assert any(isinstance(s, StuckSignal) for s in signals)


@pytest.mark.asyncio
async def test_engine_auto_steers_on_worker_blocker(tmp_path, monkeypatch):
    """Worker raises WorkerBlocker on attempt 1, analyser returns auto_steer, attempt 2 succeeds."""
    import trinity_pilot.orchestrator.engine as engine_mod
    from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator
    from trinity_pilot.orchestrator.signals import SteeringMessage, ObjectiveDone

    worker = _SuccessOnSecondWorker()
    analyser = _make_auto_steer_analyser()

    monkeypatch.setattr(engine_mod, "GeminiProvider", lambda **kwargs: object())
    monkeypatch.setattr(engine_mod, "ObjectiveReviewer", _Reviewer)
    async def dispatch(self, domain, spec):
        return await worker.execute(spec)

    monkeypatch.setattr(engine_mod.MCPClientPool, "dispatch", dispatch)
    monkeypatch.setattr(engine_mod, "OrchestratorAnalyser", lambda llm: analyser)

    db_path = tmp_path / "state.db"
    orchestrator = AsyncTaskOrchestrator(
        _make_settings(),
        db_path=str(db_path),
    )

    spec = _spec()
    spec.max_attempts = 3
    result = await orchestrator.run("do something", task_id="task-steer", objectives=[spec])

    assert result["status"] == "completed"

    # Check SteeringMessage was emitted
    signals = []
    while not orchestrator.signals.empty():
        signals.append(orchestrator.signals.get_nowait())
    assert any(isinstance(s, SteeringMessage) for s in signals)
    assert any(isinstance(s, ObjectiveDone) for s in signals)
