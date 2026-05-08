from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from trinity_pilot.workflow.activities import (
        execute_objective,
        persist_attempt,
        plan_objectives,
        review_objective,
        save_reflection_activity,
    )

_MAX_ATTEMPTS = 3
_PLAN_TIMEOUT = timedelta(minutes=5)
_EXECUTE_TIMEOUT = timedelta(minutes=10)
_REVIEW_TIMEOUT = timedelta(minutes=2)
_PERSIST_TIMEOUT = timedelta(seconds=30)
_NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class TaskWorkflow:
    def __init__(self) -> None:
        self._cancelled = False
        self._current_objective: str = ""

    @workflow.run
    async def run(self, user_request: str) -> dict:
        task_id: str = workflow.info().workflow_id

        objective_dicts: list[dict] = await workflow.execute_activity(
            plan_objectives,
            user_request,
            start_to_close_timeout=_PLAN_TIMEOUT,
            retry_policy=_NO_RETRY,
        )

        results: dict[str, dict] = {}
        prior_reflections: list[dict] = []

        for spec_dict in objective_dicts:
            obj_id: str = spec_dict["objective_id"]
            self._current_objective = obj_id
            passed = False
            prior_reflections = []
            max_attempts = int(spec_dict.get("max_attempts", _MAX_ATTEMPTS))

            for attempt in range(1, max_attempts + 1):
                if self._cancelled:
                    return {"status": "cancelled", "results": results}

                # Inject retry context from prior reflections
                attempt_spec = dict(spec_dict)
                if prior_reflections:
                    import json as _json
                    attempt_spec["retry_context"] = _json.dumps(prior_reflections)

                evidence: dict = await workflow.execute_activity(
                    execute_objective,
                    attempt_spec,
                    start_to_close_timeout=_EXECUTE_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )

                review: dict = await workflow.execute_activity(
                    review_objective,
                    args=[spec_dict, evidence],
                    start_to_close_timeout=_REVIEW_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )

                # Persist attempt evidence
                await workflow.execute_activity(
                    persist_attempt,
                    args=[
                        task_id,
                        obj_id,
                        attempt,
                        "passed" if review.get("passed") else "failed",
                        evidence,
                        review.get("failure_reason"),
                    ],
                    start_to_close_timeout=_PERSIST_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )

                if review.get("passed"):
                    results[obj_id] = {"status": "passed", "evidence": evidence}
                    passed = True
                    break

                # Save reflection for retry context
                await workflow.execute_activity(
                    save_reflection_activity,
                    args=[
                        task_id,
                        obj_id,
                        attempt,
                        review.get("failure_reason"),
                        review.get("notes", ""),
                        review.get("recovery_hint", ""),
                    ],
                    start_to_close_timeout=_PERSIST_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )

                prior_reflections.append({
                    "attempt": attempt,
                    "failure_reason": review.get("failure_reason"),
                    "notes": review.get("notes", ""),
                    "recovery_hint": review.get("recovery_hint", ""),
                })

                results[obj_id] = {
                    "status": f"attempt_{attempt}_failed",
                    "reason": review.get("failure_reason"),
                }

            if not passed:
                return {
                    "status": "failed",
                    "failed_objective": obj_id,
                    "results": results,
                }

        return {"status": "completed", "results": results}

    @workflow.signal
    def cancel(self) -> None:
        self._cancelled = True

    @workflow.query
    def get_status(self) -> str:
        return "cancelled" if self._cancelled else "running"

    @workflow.query
    def current_objective(self) -> str:
        return self._current_objective
