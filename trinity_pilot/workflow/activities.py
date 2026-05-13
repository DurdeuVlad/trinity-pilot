from __future__ import annotations

import os
import uuid
from typing import Any

from temporalio import activity

from trinity_pilot.core.types import AttemptLog, FailureReason, ObjectiveSpec
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.planner.planner import ObjectivePlanner, PlanningError
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.router import WorkerRouter


def _planner_provider() -> GeminiProvider:
    return GeminiProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.0-flash"),
    )


def _reviewer_provider() -> GeminiProvider:
    return GeminiProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
    )


@activity.defn
async def plan_objectives(user_request: str) -> list[dict[str, Any]]:
    try:
        planner = ObjectivePlanner(provider=_planner_provider())
        specs = await planner.plan(user_request)
        return [s.to_dict() for s in specs]
    except PlanningError as exc:
        from temporalio.exceptions import ApplicationError
        raise ApplicationError("planning_failed", str(exc), non_retryable=True) from exc


@activity.defn
async def execute_objective(spec_dict: dict[str, Any]) -> dict[str, Any]:
    spec = ObjectiveSpec.from_dict(spec_dict)
    router = WorkerRouter()
    try:
        worker = router.route(spec)
        evidence = await worker.execute(spec)
    except WorkerError as exc:
        evidence = {
            "domain": spec.domain.value,
            "objective_id": spec.objective_id,
            "error": str(exc),
            "passed": False,
            "failure_reason": None,
            "notes": "",
            "recovery_hint": "",
        }
        try:
            reviewer = ObjectiveReviewer(provider=_reviewer_provider())
            result = await reviewer.review(spec=spec, evidence=evidence)
            evidence["passed"] = result.passed
            evidence["failure_reason"] = result.failure_reason.value if result.failure_reason else None
            evidence["notes"] = result.notes
            evidence["recovery_hint"] = result.recovery_hint
        except Exception:
            pass
        return evidence

    reviewer = ObjectiveReviewer(provider=_reviewer_provider())
    result = await reviewer.review(spec=spec, evidence=evidence)
    evidence["passed"] = result.passed
    evidence["failure_reason"] = result.failure_reason.value if result.failure_reason else None
    evidence["notes"] = result.notes
    evidence["recovery_hint"] = result.recovery_hint
    return evidence


@activity.defn
async def persist_attempt(
    task_id: str,
    objective_id: str,
    attempt_number: int,
    status: str,
    evidence: dict[str, Any],
    failure_reason: str | None,
) -> str:
    from trinity_pilot.memory.evidence_store import EvidenceStore
    store = EvidenceStore(db_path=os.getenv("DB_PATH", "trinity_pilot.db"))
    attempt_id = str(uuid.uuid4())
    fr = FailureReason(failure_reason) if failure_reason else None
    log = AttemptLog(
        attempt_id=attempt_id,
        objective_id=objective_id,
        task_id=task_id,
        attempt_number=attempt_number,
        status=status,
        failure_reason=fr,
        evidence=evidence,
    )
    store.save(log)
    return attempt_id


@activity.defn
async def save_reflection_activity(
    task_id: str,
    objective_id: str,
    attempt_number: int,
    failure_reason: str | None,
    notes: str,
    recovery_hint: str,
) -> None:
    from trinity_pilot.memory.reflection import ReflectionStore
    store = ReflectionStore(db_path=os.getenv("DB_PATH", "trinity_pilot.db"))
    store.save_reflection(
        objective_id=objective_id,
        task_id=task_id,
        attempt_number=attempt_number,
        failure_reason=failure_reason,
        notes=notes,
        recovery_hint=recovery_hint,
    )


@activity.defn
async def update_task_status_activity(task_id: str, status_str: str) -> None:
    """Write the final task status back to the SQLite task store."""
    from trinity_pilot.core.types import TaskStatus
    from trinity_pilot.memory.store import TaskStore
    store = TaskStore(db_path=os.getenv("DB_PATH", "trinity_pilot.db"))
    store.update_status(task_id, TaskStatus(status_str))
