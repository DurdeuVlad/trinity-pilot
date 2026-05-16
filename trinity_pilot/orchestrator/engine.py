from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from trinity_pilot.config import Settings
from trinity_pilot.core.types import (
    AttemptLog,
    FailureReason,
    ObjectiveSpec,
    TaskRecord,
    TaskStatus,
)
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.memory.reflection import ReflectionStore
from trinity_pilot.memory.store import AttemptStore, ObjectiveStateStore, TaskStore
from trinity_pilot.orchestrator.budget import BudgetExceeded, ObjectiveBudget
from trinity_pilot.orchestrator.fsm import ObjectiveState
from trinity_pilot.orchestrator.signals import (
    BudgetWarning,
    ObjectiveDone,
    ObjectiveFailed,
    ObjectiveStarted,
    Signal,
    StepCompleted,
    SteeringMessage,
    StuckSignal,
)
from trinity_pilot.orchestrator.analyser import OrchestratorAnalyser, SteerDecision
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.router import WorkerRouter
from trinity_pilot.workers.worker_result import WorkerResult


@dataclass
class OrchestratorSnapshot:
    current_objective: str | None = None
    completed_objectives: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING


class AsyncTaskOrchestrator:
    """Local asyncio task orchestrator."""

    def __init__(
        self,
        settings: Settings,
        *,
        db_path: str | None = None,
        signals: asyncio.Queue[Signal] | None = None,
    ) -> None:
        self._settings = settings
        self._db_path = db_path or settings.db_path
        self.signals: asyncio.Queue[Signal] = signals or asyncio.Queue()
        self._task_store = TaskStore(self._db_path)
        self._attempt_store = AttemptStore(self._db_path)
        self._reflection_store = ReflectionStore(self._db_path)
        self._objective_store = ObjectiveStateStore(self._db_path)
        self._router = WorkerRouter()
        self._cancel_requested = asyncio.Event()
        self._snapshot = OrchestratorSnapshot()

    @property
    def snapshot(self) -> OrchestratorSnapshot:
        return OrchestratorSnapshot(
            current_objective=self._snapshot.current_objective,
            completed_objectives=list(self._snapshot.completed_objectives),
            status=self._snapshot.status,
        )

    def cancel(self) -> None:
        self._cancel_requested.set()

    async def plan(self, user_request: str) -> list[ObjectiveSpec]:
        provider = GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_planner_model,
        )
        return await ObjectivePlanner(provider).plan(user_request)

    async def run(
        self,
        user_request: str,
        *,
        task_id: str | None = None,
        objectives: list[ObjectiveSpec] | None = None,
    ) -> dict[str, Any]:
        task_id = task_id or str(uuid.uuid4())
        self._snapshot.status = TaskStatus.RUNNING
        self._task_store.save_task(
            TaskRecord(
                task_id=task_id,
                user_request=user_request,
                objectives=objectives or [],
                status=TaskStatus.RUNNING,
            )
        )

        try:
            planned = objectives if objectives is not None else await self.plan(user_request)
            self._task_store.save_task(
                TaskRecord(
                    task_id=task_id,
                    user_request=user_request,
                    objectives=planned,
                    status=TaskStatus.RUNNING,
                )
            )
            results: dict[str, Any] = {}
            for spec in planned:
                if self._cancel_requested.is_set():
                    return self._finish(task_id, TaskStatus.CANCELLED, results)
                results[spec.objective_id] = await self._run_objective(task_id, spec)
                if results[spec.objective_id]["status"] != "passed":
                    return self._finish(task_id, TaskStatus.FAILED, results)
            return self._finish(task_id, TaskStatus.COMPLETED, results)
        except asyncio.CancelledError:
            self.cancel()
            return self._finish(task_id, TaskStatus.CANCELLED, {})
        except Exception as exc:  # noqa: BLE001
            self._task_store.update_status(task_id, TaskStatus.FAILED)
            self._snapshot.status = TaskStatus.FAILED
            return {"task_id": task_id, "status": "failed", "error": str(exc)}

    async def _run_objective(self, task_id: str, spec: ObjectiveSpec) -> dict[str, Any]:
        budget = ObjectiveBudget.default()
        objective_id = spec.objective_id
        self._snapshot.current_objective = objective_id
        self._objective_store.upsert(task_id, objective_id, ObjectiveState.RUNNING)
        await self.signals.put(ObjectiveStarted(task_id, objective_id))

        worker = self._router.route(spec)
        worker._signals_queue = self.signals
        worker._task_id = task_id
        reviewer_provider = GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_worker_model,
        )
        reviewer = ObjectiveReviewer(reviewer_provider)
        analyser_provider = GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_worker_model,
        )
        analyser = OrchestratorAnalyser(analyser_provider)
        last_evidence: dict[str, Any] = {}
        retry_context: list[dict[str, Any]] = []

        for attempt_number in range(1, spec.max_attempts + 1):
            if self._cancel_requested.is_set():
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    failure_reason="cancelled",
                )
                return {"status": "cancelled", "attempts": attempt_number - 1}

            attempt_id = str(uuid.uuid4())
            if retry_context:
                spec.metadata["retry_context"] = retry_context
                spec.metadata["steering_context"] = {
                    "source": "reviewer_reflection",
                    "latest_recovery_hint": retry_context[-1].get("recovery_hint", ""),
                    "latest_reflection_id": retry_context[-1].get("reflection_id", ""),
                }
            self._attempt_store.log_attempt(
                AttemptLog(attempt_id, objective_id, task_id, attempt_number, "running")
            )
            try:
                budget.charge_step()
                evidence = await worker.execute(spec)
                last_evidence = dict(evidence)
                # If worker definitively failed, skip reviewer -- no need to retry
                if evidence.get("worker_result_status") == "failure":
                    failure_summary = evidence.get("worker_result_summary", "Worker declared definitive failure")
                    self._attempt_store.log_attempt(
                        AttemptLog(
                            attempt_id, objective_id, task_id, attempt_number, "failed",
                            FailureReason.FAILED_ASSERTION,
                            {**evidence, "worker_declared_failure": True},
                        )
                    )
                    self._objective_store.upsert(
                        task_id, objective_id, ObjectiveState.FAILED,
                        step_count=budget.steps_used(), token_count=budget.tokens_used(),
                        failure_reason="worker_declared_failure",
                    )
                    await self.signals.put(ObjectiveFailed(task_id, objective_id, "worker_declared_failure"))
                    return {"status": "failed", "failure_reason": "worker_declared_failure", "evidence": evidence}
                await self.signals.put(
                    StepCompleted(
                        task_id,
                        objective_id,
                        attempt_number,
                        spec.domain.value,
                        str(hash(repr(sorted(last_evidence.items())))),
                        0,
                    )
                )
                review = await reviewer.review(spec, last_evidence)
                if review.passed:
                    self._attempt_store.log_attempt(
                        AttemptLog(
                            attempt_id,
                            objective_id,
                            task_id,
                            attempt_number,
                            "passed",
                            evidence={**last_evidence, "notes": review.notes},
                        )
                    )
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.DONE,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                    )
                    self._snapshot.completed_objectives.append(objective_id)
                    await self.signals.put(ObjectiveDone(task_id, objective_id))
                    return {"status": "passed", "attempts": attempt_number, "evidence": last_evidence}

                reason = review.failure_reason or FailureReason.FAILED_ASSERTION
                reflection_id = self._reflection_store.save_reflection(
                    objective_id=objective_id,
                    task_id=task_id,
                    attempt_number=attempt_number,
                    failure_reason=reason.value,
                    notes=review.notes,
                    recovery_hint=review.recovery_hint,
                )
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id,
                        objective_id,
                        task_id,
                        attempt_number,
                        "failed",
                        reason,
                        {
                            **last_evidence,
                            "notes": review.notes,
                            "reviewer": {
                                "passed": review.passed,
                                "failure_reason": reason.value,
                                "notes": review.notes,
                                "recovery_hint": review.recovery_hint,
                            },
                            "recovery_hint": review.recovery_hint,
                            "reflection_id": reflection_id,
                            "reflection_storage": f"sqlite:{self._db_path}#reflections/{reflection_id}",
                        },
                    )
                )
                retry_context = self._reflection_store.get_reflections(objective_id)
                await self.signals.put(
                    SteeringMessage(
                        task_id,
                        objective_id,
                        review.recovery_hint or "Retry with reviewer reflection context",
                    )
                )
            except BudgetExceeded as exc:
                await self.signals.put(BudgetWarning(task_id, objective_id, exc.budget_type))
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    failure_reason=exc.budget_type,
                )
                await self.signals.put(ObjectiveFailed(task_id, objective_id, exc.budget_type))
                return {"status": "failed", "failure_reason": exc.budget_type}
            except WorkerBlocker as exc:
                last_evidence = {**exc.result.evidence, "blocker_reason": str(exc)}
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id,
                        objective_id,
                        task_id,
                        attempt_number,
                        "failed",
                        FailureReason.ENVIRONMENT_DIVERGENCE,
                        last_evidence,
                    )
                )
                retry_context = self._reflection_store.get_reflections(objective_id)
                steer: SteerDecision = await self._analyse_and_steer(
                    analyser, spec, retry_context, str(exc)
                )
                if steer.action == "auto_steer":
                    spec.metadata.setdefault("steering_context", {})
                    if isinstance(spec.metadata["steering_context"], dict):
                        spec.metadata["steering_context"]["latest_recovery_hint"] = steer.guidance
                    else:
                        spec.metadata["steering_context"] = {"latest_recovery_hint": steer.guidance}
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.STUCK,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                    )
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.STEERED,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                    )
                    await self.signals.put(
                        SteeringMessage(
                            task_id,
                            objective_id,
                            steer.guidance or "Retrying with auto-steer guidance",
                        )
                    )
                    continue  # next iteration of for attempt_number loop
                else:  # ask_user
                    question = steer.question or "The worker encountered a blocker. Please advise on how to proceed."
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.STUCK,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                        user_question=question,
                    )
                    await self.signals.put(
                        StuckSignal(
                            task_id,
                            objective_id,
                            "worker_blocker",
                            attempt_number,
                            question,
                        )
                    )
                    return {"status": "failed", "failure_reason": "blocker_needs_user_input"}
            except WorkerError as exc:
                last_evidence = {"error": str(exc)}
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id,
                        objective_id,
                        task_id,
                        attempt_number,
                        "failed",
                        FailureReason.ENVIRONMENT_DIVERGENCE,
                        last_evidence,
                    )
                )

            stuck = attempt_number >= getattr(self._settings, "stuck_threshold_steps", 5)
            if stuck:
                question = "The objective is not making progress. Adjust the objective or stop?"
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.STUCK,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    user_question=question,
                )
                await self.signals.put(
                    StuckSignal(task_id, objective_id, "repeated_failed_attempts", attempt_number, question)
                )

        self._objective_store.upsert(
            task_id,
            objective_id,
            ObjectiveState.FAILED,
            step_count=budget.steps_used(),
            token_count=budget.tokens_used(),
            failure_reason="max_attempts_exceeded",
        )
        await self.signals.put(ObjectiveFailed(task_id, objective_id, "max_attempts_exceeded"))
        return {"status": "failed", "attempts": spec.max_attempts, "evidence": last_evidence}

    async def _analyse_and_steer(
        self,
        analyser: OrchestratorAnalyser,
        spec: ObjectiveSpec,
        retry_context: list[dict],
        blocker_reason: str,
    ) -> SteerDecision:
        """Call the analyser with a 15-second timeout; fall back to auto_steer on any failure."""
        try:
            return await asyncio.wait_for(
                analyser.analyse(spec, retry_context, blocker_reason),
                timeout=15.0,
            )
        except Exception:
            return SteerDecision(action="auto_steer", guidance=blocker_reason)

    def _finish(
        self,
        task_id: str,
        status: TaskStatus,
        results: dict[str, Any],
    ) -> dict[str, Any]:
        self._task_store.update_status(task_id, status)
        self._snapshot.current_objective = None
        self._snapshot.status = status
        return {"task_id": task_id, "status": status.value, "results": results}
