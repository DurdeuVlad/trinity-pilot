from __future__ import annotations

import asyncio
import time

from trinity_pilot.config import Settings
from trinity_pilot.core.types import DomainType, ObjectiveSpec, ReviewResult, RiskClass, TaskStatus
from trinity_pilot.memory.store import ObjectiveStateStore, TaskStore
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator
from trinity_pilot.orchestrator.scheduler import DAGScheduler
from trinity_pilot.orchestrator.signals import ObjectiveDone, ObjectiveStarted, StepCompleted


def _spec(
    objective_id: str = "obj-1",
    *,
    domain: DomainType = DomainType.TERMINAL,
    dependencies: list[str] | None = None,
    risk_class: RiskClass = RiskClass.LOW,
) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id=objective_id,
        goal=f"run {objective_id}",
        dependencies=dependencies or [],
        domain=domain,
        required_capabilities=["terminal"],
        risk_class=risk_class,
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


class _Analyser:
    async def analyse(
        self,
        spec: ObjectiveSpec,
        retry_context: list[dict],
        blocker_reason: str,
    ):
        from trinity_pilot.orchestrator.analyser import SteerDecision

        return SteerDecision(action="auto_steer", guidance=f"retry: {blocker_reason}")


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


async def test_analyse_and_steer_low_risk_uses_tighter_timeout(tmp_path, monkeypatch):
    import trinity_pilot.orchestrator.engine as engine

    timeouts: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(engine.asyncio, "wait_for", fake_wait_for)
    orchestrator = AsyncTaskOrchestrator(
        Settings(gemini_api_key="fake-key"),
        db_path=str(tmp_path / "state.db"),
    )

    decision = await orchestrator._analyse_and_steer(
        _Analyser(),
        _spec(risk_class=RiskClass.LOW),
        [],
        "low-risk blocker",
    )

    assert decision.action == "auto_steer"
    assert timeouts == [8.0]
    assert timeouts[0] < 15.0


async def test_analyse_and_steer_medium_risk_keeps_timeout_and_failure_fallback(tmp_path, monkeypatch):
    import inspect
    import trinity_pilot.orchestrator.engine as engine

    timeouts: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise TimeoutError("analyser timed out")

    monkeypatch.setattr(engine.asyncio, "wait_for", fake_wait_for)
    orchestrator = AsyncTaskOrchestrator(
        Settings(gemini_api_key="fake-key"),
        db_path=str(tmp_path / "state.db"),
    )

    decision = await orchestrator._analyse_and_steer(
        _Analyser(),
        _spec(risk_class=RiskClass.MEDIUM),
        [],
        "medium-risk blocker",
    )

    assert decision.action == "auto_steer"
    assert decision.guidance == "medium-risk blocker"
    assert timeouts == [15.0]


async def test_dag_scheduler_completes_independent_objectives_in_parallel():
    specs = [
        _spec("browser", domain=DomainType.BROWSER),
        _spec("terminal", domain=DomainType.TERMINAL),
    ]
    durations = {"browser": 0.05, "terminal": 0.10}

    async def runner(spec: ObjectiveSpec) -> dict:
        await asyncio.sleep(durations[spec.objective_id])
        return {"status": "passed", "evidence": {"worker_result_summary": spec.objective_id}}

    started = time.monotonic()
    results = await DAGScheduler(specs, runner).run()
    elapsed = time.monotonic() - started

    assert {objective_id: result["status"] for objective_id, result in results.items()} == {
        "browser": "passed",
        "terminal": "passed",
    }
    assert elapsed < max(durations.values()) * 1.25


async def test_dag_scheduler_respects_exclusive_domains():
    specs = [
        _spec("browser", domain=DomainType.BROWSER),
        _spec("terminal", domain=DomainType.TERMINAL),
        _spec("desktop", domain=DomainType.DESKTOP),
    ]
    durations = {"browser": 0.05, "terminal": 0.05, "desktop": 0.05}
    active_count = 0
    max_active_during_desktop = 0

    async def runner(spec: ObjectiveSpec) -> dict:
        nonlocal active_count, max_active_during_desktop
        active_count += 1
        if spec.domain == DomainType.DESKTOP:
            max_active_during_desktop = max(max_active_during_desktop, active_count)
        await asyncio.sleep(durations[spec.objective_id])
        active_count -= 1
        return {"status": "passed", "evidence": {"worker_result_summary": spec.objective_id}}

    started = time.monotonic()
    results = await DAGScheduler(specs, runner).run()
    elapsed = time.monotonic() - started

    assert {objective_id: result["status"] for objective_id, result in results.items()} == {
        "browser": "passed",
        "terminal": "passed",
        "desktop": "passed",
    }
    # desktop ran sequentially: total time should be browser/terminal parallel (0.05) + desktop (0.05) = 0.10s
    assert elapsed >= 0.09
    # when desktop was running, it was the ONLY task running (count == 1)
    assert max_active_during_desktop == 1


async def test_dag_scheduler_race_does_not_duplicate_dispatch():
    for _ in range(50):
        specs = [
            _spec("browser", domain=DomainType.BROWSER),
            _spec("terminal", domain=DomainType.TERMINAL),
        ]
        dispatched: list[str] = []

        async def runner(spec: ObjectiveSpec) -> dict:
            await asyncio.sleep(0)
            dispatched.append(spec.objective_id)
            await asyncio.sleep(0)
            return {"status": "passed", "evidence": {}}

        results = await DAGScheduler(specs, runner).run()

        assert sorted(dispatched) == ["browser", "terminal"]
        assert len(dispatched) == len(set(dispatched))
        assert set(results) == {"browser", "terminal"}


async def test_orchestrator_failure_skips_failed_subtree_but_continues_unrelated_downstream(
    tmp_path,
    monkeypatch,
):
    specs = [
        _spec("fail-a", domain=DomainType.BROWSER),
        _spec("slow-b", domain=DomainType.TERMINAL),
        _spec("blocked-c", domain=DomainType.DESKTOP, dependencies=["fail-a"]),
        _spec("after-b", domain=DomainType.MIXED, dependencies=["slow-b"]),
    ]
    started: list[str] = []

    async def fake_run_objective(self, task_id: str, spec: ObjectiveSpec) -> dict:
        started.append(spec.objective_id)
        if spec.objective_id == "fail-a":
            await asyncio.sleep(0.01)
            return {"status": "failed", "failure_reason": "boom", "evidence": {}}
        if spec.objective_id == "slow-b":
            await asyncio.sleep(0.05)
        return {"status": "passed", "evidence": {"worker_result_summary": spec.objective_id}}

    monkeypatch.setattr(AsyncTaskOrchestrator, "_run_objective", fake_run_objective)
    orchestrator = AsyncTaskOrchestrator(
        Settings(gemini_api_key="fake-key"),
        db_path=str(tmp_path / "state.db"),
    )

    result = await orchestrator.run("run dag", task_id="task-dag-failure", objectives=specs)

    assert result["status"] == TaskStatus.FAILED.value
    assert result["results"]["fail-a"]["status"] == "failed"
    assert result["results"]["slow-b"]["status"] == "passed"
    assert result["results"]["after-b"]["status"] == "passed"
    assert result["results"]["blocked-c"]["status"] == "skipped"
    assert result["results"]["blocked-c"]["blocked_by"] == "fail-a"
    assert "blocked-c" not in started
    assert "after-b" in started
