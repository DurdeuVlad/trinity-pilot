from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

from trinity_pilot.config import Settings
from trinity_pilot.core.types import (
    AttemptLog,
    FailureReason,
    ObjectiveSpec,
    RiskClass,
    TaskRecord,
    TaskStatus,
)
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.llm.openai import OpenAIProvider
from trinity_pilot.mcp.client_pool import MCPClientPool
from trinity_pilot.memory.reflection import ReflectionStore
from trinity_pilot.memory.store import AttemptStore, ObjectiveStateStore, TaskStore
from trinity_pilot.orchestrator.analyser import OrchestratorAnalyser, SteerDecision
from trinity_pilot.orchestrator.budget import BudgetExceeded, ObjectiveBudget
from trinity_pilot.orchestrator.fsm import ObjectiveState
from trinity_pilot.orchestrator.scheduler import DAGScheduler
from trinity_pilot.orchestrator.signals import (
    BudgetWarning,
    ObjectiveDone,
    ObjectiveFailed,
    ObjectiveStarted,
    Signal,
    SteeringMessage,
    StepCompleted,
    StuckSignal,
)
from trinity_pilot.planner.dag import infer_cross_domain_independence, resolve_execution_order
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer, ReviewError
from trinity_pilot.telemetry.trace import emit_error
from trinity_pilot.workers.base import WorkerBlocker, WorkerError

# Evidence keys safe to forward into a dependent objective's prompt context —
# small, text-only facts a downstream worker needs (e.g. a captured page title).
# Excludes large/binary fields (screenshot, dom_snapshot) that would bloat the
# next objective's LLM context without adding anything it can act on.
_PORTABLE_EVIDENCE_KEYS = (
    "page_title",
    "page_url",
    "written_files",
    "written_files_verified",
    "created_files",
    "worker_result_summary",
    "visible_text",
    "stdout",
    "exit_code",
    "workspace",
)


def _resolve_dependency_templates(value: Any, dependency_evidence: dict[str, dict[str, Any]]) -> Any:
    """Resolve planner references to output from prerequisite objectives."""
    if isinstance(value, dict):
        return {key: _resolve_dependency_templates(item, dependency_evidence) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_dependency_templates(item, dependency_evidence) for item in value]
    if not isinstance(value, str):
        return value

    import re

    def replace(match: re.Match[str]) -> str:
        objective_id, field = match.group(1), match.group(2)
        found = dependency_evidence.get(objective_id, {}).get(field)
        return str(found) if found is not None else match.group(0)

    return re.sub(r"\{\{dependency:([^:}]+):([^}]+)\}\}", replace, value)


def _portable_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Extract the small, text-only subset of an objective's evidence that's
    safe and useful to forward into a dependent objective's prompt context."""
    portable: dict[str, Any] = {
        k: v for k, v in evidence.items()
        if k in _PORTABLE_EVIDENCE_KEYS or k.startswith("file_content_")
    }
    return portable


def _cleanup_terminal_workspaces(results: dict[str, Any]) -> None:
    """Remove terminal worker temp workspaces after the DAG (and dependents) finish.

    BH-001: workers no longer rmtree in their own finally; the orchestrator owns
    lifecycle so portable evidence stays readable until task end.
    """
    for result in results.values():
        if not isinstance(result, dict):
            continue
        evidence = result.get("evidence") or {}
        workspace = evidence.get("workspace")
        if isinstance(workspace, str) and workspace and "trinity-term-" in workspace:
            shutil.rmtree(workspace, ignore_errors=True)


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
        self._mcp_pool = MCPClientPool()
        # A prior run that crashed (process kill, power loss) can leave a task/
        # objective stuck at RUNNING forever with nothing checking it later.
        # Sweep those on every fresh orchestrator so state never silently stays
        # inconsistent across a restart.
        interrupted_tasks = self._task_store.mark_orphaned_running_as_interrupted()
        interrupted_objectives = self._objective_store.mark_orphaned_running_as_interrupted()
        if interrupted_tasks or interrupted_objectives:
            emit_error(
                "engine.py:__init__", "orphaned_state_interrupted",
                {"task_ids": interrupted_tasks, "objective_pairs": interrupted_objectives},
            )
        self._cancel_requested = asyncio.Event()
        self._active_dispatch_tasks: set[asyncio.Task[Any]] = set()
        self._snapshot = OrchestratorSnapshot()

    @property
    def snapshot(self) -> OrchestratorSnapshot:
        return OrchestratorSnapshot(
            current_objective=self._snapshot.current_objective,
            completed_objectives=list(self._snapshot.completed_objectives),
            status=self._snapshot.status,
        )

    def _build_provider(self, role: str):
        if self._settings.llm_provider == "openai":
            return OpenAIProvider(
                api_key=self._settings.openai_api_key,
                model=self._settings.openai_model,
                default_timeout=self._settings.openai_timeout_seconds,
            )
        model = self._settings.gemini_planner_model if role == "planner" else self._settings.gemini_worker_model
        return GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=model,
            default_timeout=self._settings.gemini_timeout_seconds,
        )

    def cancel(self) -> None:
        self._cancel_requested.set()
        # Cancel the task wrapping each active MCP call.  This makes Stop
        # interrupt a blocked browser/desktop/terminal dispatch immediately;
        # the run() finally block still owns orderly MCP pool shutdown.
        for dispatch_task in tuple(self._active_dispatch_tasks):
            if not dispatch_task.done():
                dispatch_task.cancel()

    async def plan(self, user_request: str) -> list[ObjectiveSpec]:
        provider = self._build_provider("planner")
        return await ObjectivePlanner(provider).plan(user_request)

    async def run(
        self,
        user_request: str,
        *,
        task_id: str | None = None,
        objectives: list[ObjectiveSpec] | None = None,
    ) -> dict[str, Any]:
        from trinity_pilot.telemetry.trace import emit

        task_id = task_id or str(uuid.uuid4())
        emit(
            "engine.py:run",
            "orchestrator_run_start",
            {"task_id": task_id, "request_preview": user_request[:120]},
            span="orchestrator",
        )
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
            raw_plan = objectives if objectives is not None else await self.plan(user_request)
            planned = infer_cross_domain_independence(resolve_execution_order(raw_plan))
            self._task_store.save_task(
                TaskRecord(
                    task_id=task_id,
                    user_request=user_request,
                    objectives=planned,
                    status=TaskStatus.RUNNING,
                )
            )
            results: dict[str, Any] = {}

            async def run_scheduled_objective(spec: ObjectiveSpec) -> dict[str, Any]:
                if self._cancel_requested.is_set():
                    return {"status": "cancelled", "failure_reason": "cancelled"}
                dep_ids = list(spec.dependencies or [])
                if dep_ids:
                    # Safe under concurrent dispatch: the scheduler only starts
                    # this objective after dependencies are complete, and each
                    # objective writes exclusively to results[objective_id].
                    dep_evidence = {
                        dep_id: _portable_evidence(results[dep_id].get("evidence", {}))
                        for dep_id in dep_ids
                        if dep_id in results
                    }
                    if dep_evidence:
                        spec.metadata["dependency_evidence"] = dep_evidence
                        spec.metadata = _resolve_dependency_templates(spec.metadata, dep_evidence)
                return await self._run_objective(task_id, spec)

            scheduler = DAGScheduler(planned, run_scheduled_objective, results=results)
            await scheduler.run()
            if any(result.get("status") == "cancelled" for result in results.values()):
                return self._finish(task_id, TaskStatus.CANCELLED, results)
            if any(result.get("status") != "passed" for result in results.values()):
                return self._finish(task_id, TaskStatus.FAILED, results)
            return self._finish(task_id, TaskStatus.COMPLETED, results)
        except asyncio.CancelledError:
            self.cancel()
            return self._finish(task_id, TaskStatus.CANCELLED, {})
        except Exception as exc:  # noqa: BLE001
            self._task_store.update_status(task_id, TaskStatus.FAILED)
            self._snapshot.status = TaskStatus.FAILED
            return {"task_id": task_id, "status": "failed", "error": str(exc)}
        finally:
            # Prefer cleaning workspaces collected on results if available.
            try:
                if "results" in locals() and isinstance(results, dict):
                    _cleanup_terminal_workspaces(results)
            except Exception:
                pass
            await self._mcp_pool.aclose()

    async def _run_objective(self, task_id: str, spec: ObjectiveSpec) -> dict[str, Any]:
        from trinity_pilot.telemetry.trace import emit

        budget = ObjectiveBudget.default()
        objective_id = spec.objective_id
        self._snapshot.current_objective = objective_id
        emit(
            "engine.py:_run_objective",
            "objective_start",
            {"task_id": task_id, "objective_id": objective_id, "domain": spec.domain.value},
            span="orchestrator",
        )
        self._objective_store.upsert(task_id, objective_id, ObjectiveState.RUNNING)
        await self.signals.put(ObjectiveStarted(task_id, objective_id))

        reviewer_provider = self._build_provider("worker")
        try:
            reviewer = ObjectiveReviewer(reviewer_provider, sensor_call=self._mcp_pool.call_sensor)
        except TypeError:  # Compatibility with narrowly mocked reviewers in integrations.
            reviewer = ObjectiveReviewer(reviewer_provider)
        analyser_provider = self._build_provider("worker")
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
                dispatch_task = asyncio.create_task(
                    self._mcp_pool.dispatch(spec.domain, spec),
                    name=f"mcp-dispatch:{task_id}:{objective_id}:{attempt_number}",
                )
                self._active_dispatch_tasks.add(dispatch_task)
                try:
                    evidence = await dispatch_task
                finally:
                    self._active_dispatch_tasks.discard(dispatch_task)
                last_evidence = dict(evidence)
                # Charge actual LLM token usage against the objective's token budget.
                # BudgetExceeded here is caught by the except clause below, same as a
                # step/wall-clock overrun.
                budget.charge_tokens(int(evidence.get("tokens_used", 0)))
                # If worker definitively failed, skip reviewer -- no need to retry
                if evidence.get("worker_result_status") == "failure":
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
                    return {
                        "status": "passed",
                        "attempts": attempt_number,
                        "evidence": last_evidence,
                        # Bubble worker finish-summary up so the UI can synthesise a reply.
                        "summary": last_evidence.get("worker_result_summary", ""),
                    }

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
                emit_error(
                    "engine.py:_run_objective", "budget_exceeded",
                    {"task_id": task_id, "objective_id": objective_id, "budget_type": exc.budget_type},
                )
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
            except asyncio.TimeoutError:
                await self.signals.put(ObjectiveFailed(task_id, objective_id, "worker_timeout"))
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    failure_reason="worker_timeout",
                )
                return {"status": "failed", "failure_reason": "worker_timeout"}
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
                emit_error(
                    "engine.py:_run_objective", "worker_error",
                    {"task_id": task_id, "objective_id": objective_id, "error": str(exc)},
                )
                # Preserve any evidence built before the error; add error field.
                last_evidence = {**last_evidence, "error": str(exc)}
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
                err_lower = str(exc).lower()
                worker_error_reason = (
                    "worker_timeout" if "timeout" in err_lower or "timed out" in err_lower else "worker_error"
                )
                # BH-009: persist FAILED (not CANCELLED) — WorkerError is a real failure.
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    failure_reason=worker_error_reason,
                )
                await self.signals.put(ObjectiveFailed(task_id, objective_id, worker_error_reason))
                return {
                    "status": "failed",
                    "failure_reason": worker_error_reason,
                    "evidence": last_evidence,
                }
            except ReviewError as exc:
                # The planner gets a JSON-repair retry for malformed/truncated LLM output;
                # the reviewer didn't, and this exception previously propagated uncaught —
                # orphaning the objective at ObjectiveState.RUNNING forever (the task-level
                # status still ended up FAILED via the outer plan loop, but this row never
                # updated). Treat exactly like WorkerError: a definitive attempt failure.
                emit_error(
                    "engine.py:_run_objective", "review_error",
                    {"task_id": task_id, "objective_id": objective_id, "error": str(exc)},
                )
                last_evidence = {**last_evidence, "error": str(exc)}
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id, objective_id, task_id, attempt_number,
                        "failed", FailureReason.ENVIRONMENT_DIVERGENCE, last_evidence,
                    )
                )
                self._objective_store.upsert(
                    task_id, objective_id, ObjectiveState.FAILED,
                    step_count=budget.steps_used(), token_count=budget.tokens_used(),
                    failure_reason="review_error",
                )
                await self.signals.put(ObjectiveFailed(task_id, objective_id, "review_error"))
                return {"status": "failed", "failure_reason": "review_error", "evidence": last_evidence}
            except Exception as exc:
                # Defense in depth: any exception not covered by the specific handlers
                # above (a bug in an unexpected code path, a new failure mode from a
                # future change) must still resolve the objective's persisted state
                # rather than leaving it orphaned at RUNNING forever.
                emit_error(
                    "engine.py:_run_objective", "unexpected_error",
                    {"task_id": task_id, "objective_id": objective_id, "error": str(exc), "exc_type": type(exc).__name__},
                )
                last_evidence = {**last_evidence, "error": str(exc)}
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id, objective_id, task_id, attempt_number,
                        "failed", FailureReason.ENVIRONMENT_DIVERGENCE, last_evidence,
                    )
                )
                self._objective_store.upsert(
                    task_id, objective_id, ObjectiveState.FAILED,
                    step_count=budget.steps_used(), token_count=budget.tokens_used(),
                    failure_reason="unexpected_error",
                )
                await self.signals.put(ObjectiveFailed(task_id, objective_id, "unexpected_error"))
                return {"status": "failed", "failure_reason": "unexpected_error", "evidence": last_evidence}

            # BH-008: stuck threshold must be reachable under default max_attempts (3).
            stuck_threshold = min(
                int(getattr(self._settings, "stuck_threshold_steps", 3) or 3),
                spec.max_attempts,
            )
            stuck = attempt_number >= stuck_threshold
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
        """Call the analyser with a risk-tier timeout; fall back to auto_steer on any failure."""
        timeout = 8.0 if spec.risk_class == RiskClass.LOW else 15.0
        try:
            return await asyncio.wait_for(
                analyser.analyse(spec, retry_context, blocker_reason),
                timeout=timeout,
            )
        except Exception:
            return SteerDecision(action="auto_steer", guidance=blocker_reason)

    def _finish(
        self,
        task_id: str,
        status: TaskStatus,
        results: dict[str, Any],
    ) -> dict[str, Any]:

        from trinity_pilot.telemetry.trace import emit, export_attempts_json

        self._task_store.update_status(task_id, status)
        self._snapshot.current_objective = None
        self._snapshot.status = status
        attempts_path = export_attempts_json(
            task_id, self._attempt_store.get_attempts_by_task(task_id)
        )
        emit(
            "engine.py:_finish",
            "orchestrator_run_finish",
            {
                "task_id": task_id,
                "status": status.value,
                "attempts_file": str(attempts_path) if attempts_path else None,
            },
            span="orchestrator",
        )

        out: dict[str, Any] = {"task_id": task_id, "status": status.value, "results": results}
        if attempts_path:
            out["attempts_file"] = str(attempts_path)
        return out

