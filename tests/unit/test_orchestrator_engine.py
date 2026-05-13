from __future__ import annotations

from trinity_pilot.config import Settings
from trinity_pilot.core.types import DomainType, ObjectiveSpec, ReviewResult, RiskClass
from trinity_pilot.memory.store import ObjectiveStateStore, TaskStore
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator
from trinity_pilot.orchestrator.signals import ObjectiveDone, ObjectiveStarted, StepCompleted


def _spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-1",
        goal="echo hello",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["stdout contains hello"],
        evidence_bundle=["stdout"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


class _Worker:
    async def execute(self, spec: ObjectiveSpec) -> dict:
        return {"stdout": "hello", "exit_code": 0}


class _Reviewer:
    def __init__(self, provider: object) -> None:
        pass

    async def review(self, spec: ObjectiveSpec, evidence: dict) -> ReviewResult:
        return ReviewResult(passed=True, notes="ok")


async def test_orchestrator_success_updates_state_and_emits_signals(tmp_path, monkeypatch):
    import trinity_pilot.orchestrator.engine as engine

    monkeypatch.setattr(engine, "GeminiProvider", lambda **kwargs: object())
    monkeypatch.setattr(engine, "ObjectiveReviewer", _Reviewer)
    monkeypatch.setattr(engine.WorkerRouter, "route", lambda self, spec: _Worker())

    db_path = tmp_path / "state.db"
    orchestrator = AsyncTaskOrchestrator(
        Settings(gemini_api_key="fake-key"),
        db_path=str(db_path),
    )

    result = await orchestrator.run("say hello", task_id="task-1", objectives=[_spec()])

    assert result["status"] == "completed"
    assert TaskStore(db_path).get_task("task-1").status.value == "completed"
    row = ObjectiveStateStore(db_path).get("task-1", "obj-1")
    assert row["state"] == "done"

    signals = [orchestrator.signals.get_nowait() for _ in range(3)]
    assert [type(s) for s in signals] == [ObjectiveStarted, StepCompleted, ObjectiveDone]
