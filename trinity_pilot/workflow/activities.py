from __future__ import annotations

import os
import uuid
from typing import Any

from temporalio import activity

from trinity_pilot.core.types import AttemptLog, FailureReason, ObjectiveSpec
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer
from trinity_pilot.workers.router import WorkerRouter


def _planner_provider() -> GeminiProvider:
    return GeminiProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-1.5-pro"),
    )


def _reviewer_provider() -> GeminiProvider:
    return GeminiProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_PLANNER_MODEL", "gemini-1.5-pro"),
    )


@activity.defn
async def plan_objectives(user_request: str) -> list[dict[str, Any]]:
    planner = ObjectivePlanner(provider=_planner_provider())
    specs = await planner.plan(user_request)
    return [s.to_dict() for s in specs]


@activity.defn
async def execute_objective(spec_dict: dict[str, Any]) -> dict[str, Any]:
    spec = ObjectiveSpec.from_dict(spec_dict)
    router = WorkerRouter()
    worker = router.route(spec)
    return await worker.execute(spec)


@activity.defn
async def review_objective(
    spec_dict: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    spec = ObjectiveSpec.from_dict(spec_dict)
    reviewer = ObjectiveReviewer(provider=_reviewer_provider())
    result = await reviewer.review(spec=spec, evidence=evidence)
    return {
        "passed": result.passed,
        "failure_reason": result.failure_reason.value if result.failure_reason else None,
        "notes": result.notes,
        "recovery_hint": result.recovery_hint,
    }


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
