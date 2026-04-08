"""Execution runner: Plan → Act → Reflect → Replan orchestration.

For each objective in the plan:
  1. ACT   — run AgentLoop.act() until done or stuck.
  2. REFLECT — ReflectionEngine evaluates if objective was truly achieved.
  3. If not achieved and attempts remain: inject critique, retry from step 1.
  4. If all attempts exhausted: record failure, call MacroPlanner.replan() to
     revise remaining objectives, then continue to the next one.

Final status: "success" (all achieved) | "partial" (some failed) | "failure" (all failed).
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .active_reviewer import ActiveReviewer, ReviewStatus
from .agent_loop import AgentLoop
from .checkpoint_manager import CheckpointManager
from .database import TaskStatus
from .execution_context import ErrorRecord, ExecutionContext
from .failure_classifier import FailureKind, classify
from .macro_planner import ExecutionPlan
from .output_validator import OutputValidator
from .prompt_registry import PromptRegistry
from .reflection_engine import ReflectionEngine

try:
    from audit_debugger import (
        AuditConfig,
        FlightRecorder,
        RuntimePerformanceTracker,
        activate_prompt_logging,
        build_situation_record,
        diff_states,
        finalize_cost_metrics,
        reset_prompt_logging,
        update_prompt_logging_context,
        write_situation_record,
        write_state_snapshot,
    )
except ImportError:  # pragma: no cover - optional dependency in some environments
    AuditConfig = None
    FlightRecorder = None
    RuntimePerformanceTracker = None
    activate_prompt_logging = None
    build_situation_record = None
    diff_states = None
    finalize_cost_metrics = None
    reset_prompt_logging = None
    update_prompt_logging_context = None
    write_situation_record = None
    write_state_snapshot = None

if TYPE_CHECKING:
    from .providers.base import LLMProvider

MAX_ATTEMPTS_PER_OBJECTIVE = 3
_ORCHESTRATOR_REPORT_OBJECTIVE_ID = "orchestrator"
_FAILURE_REPORT_PREFIXES = (
    "report ",
    "explain ",
    "inform ",
    "notify ",
    "tell the user",
)
_FAILURE_REPORT_MARKERS = (
    "could not",
    "cannot",
    "can't",
    "failed",
    "did not",
    "not found",
    "does not exist",
    "couldn't",
    "unable to",
    "unavailable",
    "missing",
)

logger = logging.getLogger(__name__)


class TaskExecutionRunner:
    """Orchestrate a task end-to-end via Plan → Act → Reflect → Replan."""

    def __init__(
        self,
        *,
        run_id: str,
        task_description: str,
        domain: str,
        event_bus: Any,
        history_manager: Any,
        error_handler: Any,
        planner: Any,
        provider: "LLMProvider",
        bridge: Any,
        screenshot_watcher: Any,
        cancel_requested: Callable[[], bool],
        cancel_event: Any,
        resume_event: Any = None,
        approved_plan: list[str] | None = None,
        provider_name: str = "gemini",
        timeout_seconds: int = 600,
        max_retries: int = 3,
        audit_recorder: Any = None,
        audit_config: Any = None,
    ) -> None:
        self.run_id = run_id
        self.task_description = task_description
        self.domain = domain
        self.event_bus = event_bus
        self.history_manager = history_manager
        self.error_handler = error_handler
        self.planner = planner
        self.provider = provider
        self.bridge = bridge
        self.screenshot_watcher = screenshot_watcher
        self.cancel_requested = cancel_requested
        self.cancel_event = cancel_event
        self.resume_event = resume_event
        self.approved_plan = [step.strip() for step in (approved_plan or []) if step.strip()]
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.audit_recorder = audit_recorder
        self.audit_config = audit_config
        self._owns_audit_recorder = False
        self._prompt_logging_token = None
        self._backend_executions: list[dict[str, Any]] = []
        self.performance_tracker = None
        self._audit_output_dir = Path(__file__).resolve().parents[1] / "_runtime" / "flight_reports"

        self.registry = PromptRegistry(provider_name)
        self.checkpoint_manager = CheckpointManager()  # uses absolute default path
        self.output_validator = OutputValidator()
        self.reflection_engine = ReflectionEngine(provider, self.registry)
        self.active_reviewer = ActiveReviewer(provider)

    async def execute(self) -> None:
        """Run the full orchestration lifecycle."""
        caught_error: Exception | None = None
        self._start_audit_recording()
        try:
            await self._initialize_run()
            plan = await self._plan_phase()
            if plan is None:
                return
            context, start_index, agent_loop = self._build_attempt_context(plan)
            result = await self._attempt_phase(plan.steps, context, start_index, agent_loop)
            if result is not None:
                completed, failed = result
                await self._finalize_phase(plan.steps, completed, failed)
        except Exception as exc:
            caught_error = exc
            self._audit_event(
                phase="system",
                message="Task execution runner raised an unhandled exception",
                level="error",
                data={"error": str(exc), "error_type": type(exc).__name__},
                importance=1,
            )
            self._set_audit_status("failure")
            raise
        finally:
            self._finish_audit_recording(caught_error)
            await self._teardown()

    # ── Phase: Initialize ──────────────────────────────────────────────────

    async def _initialize_run(self) -> None:
        """Set up bridge, watchers, and history record for the new run."""
        self._audit_event(
            phase="system",
            message="Initializing task execution runner",
            data={
                "run_id": self.run_id,
                "task_description": self.task_description,
                "domain": self.domain,
            },
            importance=2,
        )
        if self.performance_tracker is not None:
            self.performance_tracker.sample_resources(
                label="initialize",
                module="unified-app-orchestrator",
            )
        self._status("Preparing automation runtime...", "info")
        await self.bridge.initialize()
        self.screenshot_watcher.start_watching()
        self._signal("execution_started")
        self.history_manager.create_task(
            task_id=self.run_id,
            description=self.task_description,
            domain=self.domain,
            plan_steps=[],
            estimated_duration=0,
            confidence=0.0,
        )
        self.history_manager.start_task(self.run_id)
        self._status("Analyzing your task...", "thinking")
        self._status("Thinking about how to approach your task…", "thinking")

    # ── Phase: Plan ────────────────────────────────────────────────────────

    async def _plan_phase(self) -> ExecutionPlan | None:
        """Generate or restore the execution plan.

        Returns None when plan generation fails (failure is handled internally).
        """
        if self.approved_plan:
            self._audit_event(
                phase="planning",
                message="Using pre-approved plan",
                data={
                    "task_description": self.task_description,
                    "domain": self.domain,
                    "step_count": len(self.approved_plan),
                    "steps": list(self.approved_plan),
                },
                importance=2,
            )
            self._status("Using the objectives you approved before execution...", "info")
            plan = ExecutionPlan(
                description=self.task_description,
                domain=self.domain,
                steps=self.approved_plan,
                estimated_duration=len(self.approved_plan) * 60,
                confidence=0.95,
            )
        else:
            try:
                self._status("Breaking the task into objectives...", "info")
                capabilities: dict = {}
                self._audit_event(
                    phase="planning",
                    message="MacroPlanner generating plan",
                    data={
                        "task_description": self.task_description,
                        "domain": self.domain,
                        "approved_plan": False,
                    },
                    importance=2,
                )
                try:
                    capability_map = await self.bridge.get_capabilities()
                    capabilities = capability_map.get(self.domain, {}) if isinstance(capability_map, dict) else {}
                except Exception:
                    pass
                self._audit_event(
                    phase="planning",
                    message="Capability assessment complete",
                    data={
                        "domain": self.domain,
                        "capabilities": capabilities,
                    },
                    importance=3,
                )
                plan = await self.planner.generate_plan(
                    self.task_description, self.domain, capabilities=capabilities
                )
                if self.performance_tracker is not None:
                    self.performance_tracker.sample_resources(
                        label="plan_generated",
                        module="unified-app-orchestrator",
                    )
            except Exception as plan_exc:
                self._handle_plan_failure(plan_exc)
                return None

        if hasattr(self.history_manager, "update_task_plan"):
            self.history_manager.update_task_plan(
                self.run_id,
                plan_steps=plan.steps,
                estimated_duration=plan.estimated_duration,
                confidence=plan.confidence,
            )
        self._audit_event(
            phase="planning",
            message="Plan generated successfully",
            data={
                "steps": list(plan.steps),
                "estimated_duration": plan.estimated_duration,
                "confidence": plan.confidence,
                "step_count": len(plan.steps),
                "approved_plan": bool(self.approved_plan),
            },
            importance=1,
        )
        self._signal("plan_generated", plan.steps)
        n = len(plan.steps)
        self._status("Starting execution...", "info")
        self._status(f"Got it — I'll tackle this in {n} step{'s' if n != 1 else ''}.", "success")
        return plan

    # ── Phase: Build attempt context ───────────────────────────────────────

    def _build_attempt_context(self, plan: ExecutionPlan) -> tuple["ExecutionContext", int, "AgentLoop"]:
        """Restore checkpoint context or create a fresh one, then build the agent loop."""
        checkpoint_id = self.checkpoint_manager.get_latest_checkpoint(self.run_id)
        if checkpoint_id:
            self._status("Picking up where I left off…", "info")
            context, start_index = self.checkpoint_manager.load_checkpoint(checkpoint_id)
            context.objective = self.task_description
        else:
            context = ExecutionContext(objective=self.task_description)
            start_index = 0

        agent_loop = AgentLoop(
            provider=self.provider,
            bridge=self.bridge,
            emit_status=self._status,
            cancel_requested=self.cancel_requested,
            registry=self.registry,
            context=context,
            output_validator=self.output_validator,
            cancel_event=self.cancel_event,
            resume_event=self.resume_event,
            performance_tracker=self.performance_tracker,
        )
        return context, start_index, agent_loop

    # ── Phase: Attempt ─────────────────────────────────────────────────────

    async def _attempt_phase(
        self,
        plan_steps: list[str],
        context: "ExecutionContext",
        start_index: int,
        agent_loop: "AgentLoop",
    ) -> tuple[list, list] | None:
        """Drive the Act → Reflect → Replan loop for each objective.

        Returns (completed, failed) on normal termination, or None if cancelled.
        """
        objectives: list[str] = list(plan_steps)
        completed: list[tuple[int, str]] = []
        failed: list[tuple[int, str, str]] = []

        index = 0
        while index < len(objectives):
            objective = objectives[index]
            display_index = index + 1

            if display_index <= start_index:
                completed.append((display_index, objective))
                index += 1
                continue

            if self.cancel_requested():
                self._complete_as_cancelled()
                return None

            self.history_manager.add_step(self.run_id, display_index, objective)
            self._signal("step_started", display_index, objective)
            self._status(
                f"Executing objective {display_index} of {len(objectives)}...",
                "info",
            )
            self._status(f"{display_index}/{len(objectives)}|{objective}", "step")
            self.history_manager.update_step_status(
                self.run_id, display_index, TaskStatus.RUNNING
            )
            self._audit_event(
                phase="execution",
                message="Objective execution started",
                data={
                    "objective_index": display_index,
                    "objective": objective,
                    "objective_count": len(objectives),
                },
                importance=2,
            )
            if update_prompt_logging_context is not None:
                try:
                    update_prompt_logging_context(
                        extra={
                            "current_objective_id": f"objective_{display_index}",
                            "current_objective_label": objective,
                        }
                    )
                except Exception as exc:
                    logger.warning("Failed to update prompt logging objective context: %s", exc)
            objective_timer = (
                self.performance_tracker.start_action(
                    action_type="objective",
                    action_description=objective,
                    module="unified-app-orchestrator",
                    objective=objective,
                )
                if self.performance_tracker is not None
                else None
            )
            before_snapshot_state = self._build_snapshot_state(
                context=context,
                objective=objective,
                objective_index=display_index,
                payload={},
            )
            before_snapshot_path = self._write_snapshot_artifact(
                name=f"objective_{display_index}_before",
                snapshot_type="before_objective",
                state=before_snapshot_state,
            )

            objective_achieved, final_result = await self._run_attempts(
                objective, display_index, context, agent_loop
            )
            if objective_achieved is None:
                return None  # cancelled during attempts

            step_payload = dict(agent_loop.last_step_payload or {})
            if objective_achieved and _step_indicates_failure(final_result, step_payload):
                objective_achieved = False

            if objective_achieved:
                if objective_timer is not None and self.performance_tracker is not None:
                    self.performance_tracker.finish_action(
                        objective_timer,
                        status="success",
                        result_summary=final_result,
                        data={"objective_index": display_index},
                    )
                completed.append((display_index, objective))
                context.update_state(f"objective_{display_index}_desc", objective)
                context.update_state(f"objective_{display_index}_result", final_result)
                try:
                    cp_id = self.checkpoint_manager.save_checkpoint(
                        task_id=self.run_id,
                        context=context,
                        objective_index=display_index,
                    )
                    context.checkpoint_id = cp_id
                except Exception as cp_exc:
                    self._status(f"Couldn't save my progress checkpoint: {cp_exc}", "warning")

                payload = step_payload
                payload["status"] = "success"
                payload["output"] = final_result or payload.get("output", "")
                payload.setdefault("artifacts", [])
                payload.setdefault("execution_log", [])
                payload.setdefault("metadata", {})
                backend_execution = self._record_backend_execution(display_index, objective, payload)
                self._signal("step_completed", display_index, payload)
                self.history_manager.update_step_status(
                    self.run_id,
                    display_index,
                    TaskStatus.COMPLETED,
                    result_data=payload,
                    flight_report_path=backend_execution.get("flight_report_path"),
                )
                if self.performance_tracker is not None:
                    self.performance_tracker.sample_resources(
                        label=f"objective_{display_index}_complete",
                        module="unified-app-orchestrator",
                    )
                self._capture_objective_knowledge_artifacts(
                    objective=objective,
                    objective_index=display_index,
                    context=context,
                    payload=payload,
                    success=True,
                    result_text=final_result,
                    before_snapshot_state=before_snapshot_state,
                    before_snapshot_path=before_snapshot_path,
                )
            else:
                if objective_timer is not None and self.performance_tracker is not None:
                    self.performance_tracker.finish_action(
                        objective_timer,
                        status="failure",
                        result_summary=final_result,
                        data={"objective_index": display_index},
                    )
                failed.append((display_index, objective, final_result))
                payload = dict(agent_loop.last_step_payload or {})
                backend_execution = self._record_backend_execution(display_index, objective, payload)
                self._signal("step_failed", display_index, final_result)
                self._status(
                    "Couldn't complete this step after multiple attempts. Moving on…",
                    "warning",
                )
                self.history_manager.update_step_status(
                    self.run_id,
                    display_index,
                    TaskStatus.FAILED,
                    error_message=final_result,
                    flight_report_path=backend_execution.get("flight_report_path"),
                )

                remaining_tail = objectives[index + 1:]
                if remaining_tail:
                    self._audit_event(
                        phase="replanning",
                        message="Replanning triggered after objective failure",
                        level="warning",
                        data={
                            "failed_objective": objective,
                            "failed_objective_index": display_index,
                            "completed_objectives": [obj for _, obj in completed],
                            "failed_objectives": [
                                {"objective": obj, "reason": reason}
                                for _, obj, reason in failed
                            ],
                            "remaining_objectives": list(remaining_tail),
                            "learned_constraints": list(context.learned_constraints),
                        },
                        importance=1,
                    )
                    revised = await self._try_replan(
                        completed=[obj for _, obj in completed],
                        failed=[(obj, reason) for _, obj, reason in failed],
                        remaining=remaining_tail,
                        constraints=list(context.learned_constraints),
                    )
                    if revised != remaining_tail:
                        self._status(
                            "Adjusting the remaining plan based on what happened...",
                            "thinking",
                        )
                        self._status(
                            "Adjusting my plan based on what I've learned…",
                            "thinking",
                        )
                        objectives = objectives[: index + 1] + revised
                if self.performance_tracker is not None:
                    self.performance_tracker.sample_resources(
                        label=f"objective_{display_index}_failed",
                        module="unified-app-orchestrator",
                    )
                self._capture_objective_knowledge_artifacts(
                    objective=objective,
                    objective_index=display_index,
                    context=context,
                    payload=payload,
                    success=False,
                    result_text=final_result,
                    before_snapshot_state=before_snapshot_state,
                    before_snapshot_path=before_snapshot_path,
                )

            index += 1

        await agent_loop.cleanup_browser_session(0, context)
        return completed, failed

    # ── Phase: Per-objective attempts ──────────────────────────────────────

    async def _run_attempts(
        self,
        objective: str,
        display_index: int,
        context: "ExecutionContext",
        agent_loop: "AgentLoop",
    ) -> tuple[bool | None, str]:
        """Run Act → Reflect retries for one objective.

        Returns (achieved, final_result).
        achieved is None when a cancellation occurred.
        """
        objective_achieved = False
        final_result = ""
        critique = ""

        for attempt in range(MAX_ATTEMPTS_PER_OBJECTIVE):
            if self.cancel_requested():
                await agent_loop.cleanup_browser_session(display_index, context)
                self._complete_as_cancelled(active_step=display_index)
                return None, ""

            if attempt > 0:
                self._status(
                    f"Retrying objective {display_index} with a different approach...",
                    "thinking",
                )
                self._status(
                    "Hmm, that didn't quite work. Let me try a different approach…",
                    "thinking",
                )

            result = await agent_loop.act(
                objective=objective,
                obj_index=display_index,
                context=context,
                adapt_hint=critique,
            )

            if result == "[cancelled]":
                await agent_loop.cleanup_browser_session(display_index, context)
                self._complete_as_cancelled(active_step=display_index)
                return None, ""

            final_result = result

            reflection = await self.reflection_engine.reflect(
                objective=objective,
                result=result,
                attempt=attempt,
            )
            self._audit_event(
                phase="reflection",
                message="Objective reflection complete",
                data={
                    "objective": objective,
                    "objective_index": display_index,
                    "attempt": attempt + 1,
                    "achieved": reflection.achieved,
                    "critique": reflection.critique,
                    "result_summary": str(result)[:200],
                },
                importance=2,
            )

            step_payload = dict(agent_loop.last_step_payload or {})
            if reflection.achieved and _completion_lacks_execution_evidence(objective, step_payload):
                critique = (
                    "The previous attempt claimed completion without any successful execution evidence. "
                    "Actually perform the required browser, desktop, or CLI action and only finish after a concrete result is recorded."
                )
                self._status(
                    "That completion claim had no real execution evidence. Retrying…",
                    "warning",
                )
                self._audit_event(
                    phase="reflection",
                    message="Completion rejected due to missing execution evidence",
                    level="warning",
                    data={
                        "objective": objective,
                        "objective_index": display_index,
                        "attempt": attempt + 1,
                        "reason": "missing_execution_evidence",
                        "retry_hint": critique,
                    },
                    importance=1,
                )
                if hasattr(self.provider, "report_cache_failure"):
                    self.provider.report_cache_failure()
                context.add_error(ErrorRecord(
                    error_type="missing_execution_evidence",
                    error_message=critique,
                    attempted_action={"objective": objective, "attempt": attempt},
                    timestamp=time.time(),
                ))
                continue

            if reflection.achieved:
                objective_achieved = True
                break
            
            review = await self.active_reviewer.review_progress(
                objective=objective,
                completed_tasks=self._get_completed_tasks_for_review(context, display_index),
                world_state=context.world_state.__dict__ if hasattr(context, 'world_state') else {},
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS_PER_OBJECTIVE
            )
            
            if review.status == ReviewStatus.CONTINUE:
                feedback_msg = self.active_reviewer.format_feedback_for_executor(review)
                self._status(f"Reviewer feedback:\n{feedback_msg}", "info")
                self._audit_event(
                    phase="reflection",
                    message="Active reviewer requested continuation",
                    data={
                        "objective": objective,
                        "objective_index": display_index,
                        "attempt": attempt + 1,
                        "assessment": review.assessment,
                        "missing": list(review.missing),
                        "next_steps": list(review.next_steps),
                        "hints": list(review.hints),
                    },
                    importance=3,
                )
                critique = "\n".join([
                    "REVIEWER GUIDANCE:",
                    f"Assessment: {review.assessment}",
                    "What's missing: " + ", ".join(review.missing),
                    "Next steps: " + "; ".join(review.next_steps),
                    "Hints: " + "; ".join(review.hints) if review.hints else ""
                ])
                continue
            elif review.status == ReviewStatus.PIVOT:
                feedback_msg = self.active_reviewer.format_feedback_for_executor(review)
                self._status(f"Reviewer suggests pivot:\n{feedback_msg}", "warning")
                self._audit_event(
                    phase="reflection",
                    message="Active reviewer requested pivot",
                    level="warning",
                    data={
                        "objective": objective,
                        "objective_index": display_index,
                        "attempt": attempt + 1,
                        "assessment": review.assessment,
                        "alternative_strategies": list(review.alternative_strategies),
                    },
                    importance=2,
                )
                critique = "\n".join([
                    "REVIEWER SUGGESTS DIFFERENT APPROACH:",
                    f"Reason: {review.assessment}",
                    "Try these alternatives: " + "; ".join(review.alternative_strategies)
                ])
                continue

            failure_text = " ".join(
                part for part in (
                    str(final_result or ""),
                    str(reflection.critique or ""),
                    _payload_failure_text(step_payload),
                ) if part
            )
            failure_kind = classify(failure_text)
            self._status(
                f"Failure on attempt {attempt + 1} classified as {failure_kind.value}.",
                "info",
            )
            self._audit_event(
                phase="reflection",
                message="Objective retry decision evaluated",
                level="warning",
                data={
                    "objective": objective,
                    "objective_index": display_index,
                    "attempt": attempt + 1,
                    "failure_kind": failure_kind.value,
                    "critique": reflection.critique,
                },
                importance=2,
            )
            if failure_kind == FailureKind.PERMANENT or (
                failure_kind == FailureKind.AMBIGUOUS and attempt >= 1
            ):
                if _is_missing_resource_failure(final_result, step_payload):
                    critique = (
                        "The required target could not be found. Stop retrying alternate execution paths and "
                        "replan the remaining objectives around this failure."
                    )
                    error_type = "missing_resource_failure"
                    self._status(
                        "The required target could not be found. Moving to failure handling...",
                        "warning",
                    )
                    self._audit_event(
                        phase="reflection",
                        message="Permanent failure detected due to missing resource",
                        level="warning",
                        data={
                            "objective": objective,
                            "objective_index": display_index,
                            "attempt": attempt + 1,
                            "failure_kind": failure_kind.value,
                            "reason": critique,
                        },
                        importance=1,
                    )
                else:
                    critique = (
                        "This objective appears to be permanently blocked. Stop retrying and move to "
                        "failure handling and replanning."
                    )
                    error_type = "permanent_failure"
                    self._status(
                        "This objective appears permanently blocked. Moving to failure handling...",
                        "warning",
                    )
                    self._audit_event(
                        phase="reflection",
                        message="Permanent failure detected",
                        level="warning",
                        data={
                            "objective": objective,
                            "objective_index": display_index,
                            "attempt": attempt + 1,
                            "failure_kind": failure_kind.value,
                            "reason": critique,
                        },
                        importance=1,
                    )
                if hasattr(self.provider, "report_cache_failure"):
                    self.provider.report_cache_failure()
                context.add_error(ErrorRecord(
                    error_type=error_type,
                    error_message=critique,
                    attempted_action={"objective": objective, "attempt": attempt},
                    timestamp=time.time(),
                ))
                break

            critique = (
                reflection.critique
                or "The previous attempt did not fully achieve the objective. Try a different approach."
            )
            self._status("That attempt didn't fully achieve the goal. Retrying…", "warning")
            self._status(
                f"Objective {display_index} is not complete yet. Retrying...",
                "warning",
            )
            self._audit_event(
                phase="reflection",
                message="Retry triggered",
                level="warning",
                data={
                    "objective": objective,
                    "objective_index": display_index,
                    "attempt": attempt + 1,
                    "reason": critique,
                    "failure_kind": failure_kind.value,
                },
                importance=1,
            )
            if hasattr(self.provider, "report_cache_failure"):
                self.provider.report_cache_failure()
            context.add_error(ErrorRecord(
                error_type="reflection_failure",
                error_message=critique,
                attempted_action={"objective": objective, "attempt": attempt},
                timestamp=time.time(),
            ))

        return objective_achieved, final_result

    # ── Phase: Finalize ────────────────────────────────────────────────────

    async def _finalize_phase(
        self,
        plan_steps: list[str],
        completed: list[tuple[int, str]],
        failed: list[tuple[int, str, str]],
    ) -> None:
        """Compute final outcome, emit signals, and persist run record."""
        try:
            self.checkpoint_manager.delete_task_checkpoints(self.run_id)
        except Exception:
            pass

        effective_total = max(
            1,
            sum(1 for obj in plan_steps if _counts_toward_task_completion(obj)),
        )
        n_done = sum(1 for _, obj in completed if _counts_toward_task_completion(obj))
        n_failed = len(failed)

        if n_failed == 0:
            status, category = "success", "success"
            msg = "All done! Everything completed successfully."
            error_message = None
        elif n_done == 0:
            status, category = "failure", "failure"
            msg = "I wasn't able to complete this task. Try rephrasing it or check your setup."
            error_message = msg
        else:
            status, category = "partial", "partial"
            msg = f"Partially done — completed {n_done} of {effective_total} steps."
            error_message = msg

        self._signal("execution_complete", {"status": status, "category": category})
        self._set_audit_status(status)
        self._update_audit_metrics(
            completed_count=n_done,
            failed_count=n_failed,
            total_objectives=len(plan_steps),
        )
        if self.audit_recorder is not None:
            self.audit_recorder.report.diagnostics["backend_executions"] = list(self._backend_executions)
        if status == "success":
            self._status("Execution completed successfully.", "success")
        level = "done" if status == "success" else "fail"
        self._status(msg, level)

        if status == "success":
            chat_msg = f"Done! Task completed: {self.task_description}"
            if n_done > 1:
                chat_msg += f" ({n_done} steps completed)"
        elif status == "partial":
            chat_msg = f"Partially done — {n_done} of {effective_total} steps succeeded."
        else:
            chat_msg = "Task failed. Check the log below for details."
        self._signal("task_result_ready", chat_msg)

        if status == "failure" and failed:
            core = _extract_error_core(failed[0][2])
            self._status(self.error_handler.build_user_message(core), "error")

        self.history_manager.complete_task(
            self.run_id,
            result_data={"status": status, "category": category},
            error_message=error_message,
        )

    # ── Phase: Teardown ────────────────────────────────────────────────────

    async def _teardown(self) -> None:
        """Release all runtime resources regardless of how execution terminated."""
        provider_close = getattr(self.provider, "close", None)
        if callable(provider_close):
            await provider_close()
        self.screenshot_watcher.stop_watching()
        self._signal("execution_ended")
        await self.bridge.shutdown()
        self.history_manager.close()

    # ── Replan ────────────────────────────────────────────────────────────

    async def _try_replan(
        self,
        completed: list[str],
        failed: list[tuple[str, str]],
        remaining: list[str],
        constraints: list[str] | None = None,
    ) -> list[str]:
        """Attempt to replan remaining objectives. Returns original list on failure."""
        try:
            revised = await self.planner.replan(
                original_task=self.task_description,
                completed=completed,
                failed=failed,
                remaining=remaining,
                constraints=constraints or [],
            )
            revised_steps = revised if revised is not None else remaining
            self._audit_event(
                phase="replanning",
                message="Replanning complete",
                data={
                    "original_remaining": list(remaining),
                    "revised_remaining": list(revised_steps),
                    "changes_made": list(revised_steps) != list(remaining),
                    "removed_objectives": [item for item in remaining if item not in revised_steps],
                    "added_objectives": [item for item in revised_steps if item not in remaining],
                },
                importance=2,
            )
            return revised_steps
        except Exception as exc:
            self._status("Couldn't revise the plan — continuing with what I have.", "warning")
            self._audit_event(
                phase="replanning",
                message="Replanning failed",
                level="error",
                data={
                    "original_remaining": list(remaining),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                importance=1,
            )
            return remaining

    # ── Plan failure ───────────────────────────────────────────────────────

    def _handle_plan_failure(self, exc: Exception) -> None:
        error_payload = self.error_handler.handle(exc, context="Plan generation")
        mapped = self.error_handler.map_backend_unavailable_reason(
            self.domain, error_payload["message"]
        )
        if mapped:
            error_payload["user_message"] = mapped
        self._audit_event(
            phase="planning",
            message="Plan generation failed",
            level="error",
            data={
                "task_description": self.task_description,
                "domain": self.domain,
                "error": error_payload["message"],
                "error_type": type(exc).__name__,
                "user_message": error_payload["user_message"],
            },
            importance=1,
        )
        self._set_audit_status("failure")
        existing_task = self.history_manager.get_task(self.run_id) if hasattr(self.history_manager, "get_task") else None
        if existing_task is None:
            self.history_manager.create_task(
                task_id=self.run_id,
                description=self.task_description,
                domain=self.domain,
                plan_steps=[],
                estimated_duration=0,
                confidence=0.0,
            )
            self.history_manager.start_task(self.run_id)
        self.history_manager.complete_task(self.run_id, error_message=error_payload["message"])
        self._status(error_payload["user_message"], "error")
        self._signal("execution_complete", {
            "status": "failure",
            "category": error_payload["category"],
            "error": error_payload["user_message"],
        })

    # ── Cancellation ──────────────────────────────────────────────────────

    def _complete_as_cancelled(self, active_step: int | None = None) -> None:
        self._status("Stopped — cancelled by you.", "cancelled")
        self._signal("execution_complete", {"status": "cancelled", "category": "cancelled"})
        self._set_audit_status("cancelled")
        if active_step is not None:
            self.history_manager.update_step_status(
                self.run_id, active_step, TaskStatus.CANCELLED,
                error_message="Cancelled by user",
            )
        self.history_manager.complete_task(
            self.run_id,
            result_data={"status": "cancelled", "category": "cancelled"},
            error_message="Cancelled by user",
            status=TaskStatus.CANCELLED,
        )

    # ── Signal helpers ─────────────────────────────────────────────────────

    def _get_completed_tasks_for_review(self, context: "ExecutionContext", current_obj_index: int) -> list[dict]:
        """Extract completed tasks for active reviewer."""
        completed = []
        
        if hasattr(context, 'module_results'):
            for module, result in context.module_results.items():
                completed.append({
                    "description": f"{module} task",
                    "status": result.get("status", "unknown"),
                    "result": str(result.get("output", ""))[:200]
                })
        
        if hasattr(context, 'accumulated_state'):
            for key, value in context.accumulated_state.items():
                if key.startswith(f"objective_{current_obj_index}_"):
                    completed.append({
                        "description": key.replace(f"objective_{current_obj_index}_", ""),
                        "status": "success" if value else "unknown",
                        "result": str(value)[:200]
                    })
        
        return completed

    def _signal(self, event_name: str, *args) -> None:
        """Emit an event on the bus if available."""
        try:
            if self.event_bus:
                getattr(self.event_bus, event_name).emit(*args)
        except RuntimeError:
            pass

    def _status(self, message: str, level: str) -> None:
        try:
            self.event_bus.emit_status(message, level)
        except RuntimeError:
            pass

    def _start_audit_recording(self) -> None:
        if self.audit_recorder is not None:
            if self._prompt_logging_token is None and activate_prompt_logging is not None:
                try:
                    self._prompt_logging_token = activate_prompt_logging(
                        recorder=self.audit_recorder,
                        config=self.audit_config,
                        module="unified-app-orchestrator",
                        session_id=self.run_id,
                        objective_id=_ORCHESTRATOR_REPORT_OBJECTIVE_ID,
                    )
                except Exception as exc:
                    logger.warning("Failed to activate prompt logging context: %s", exc)
            return
        if FlightRecorder is None or AuditConfig is None:
            return
        try:
            config = self.audit_config or AuditConfig(output_dir=str(self._audit_output_dir))
            self.audit_recorder = FlightRecorder.start(
                module="unified-app-orchestrator",
                objective={
                    "description": self.task_description,
                    "domain": self.domain,
                    "run_id": self.run_id,
                },
                session_id=self.run_id,
                objective_id=_ORCHESTRATOR_REPORT_OBJECTIVE_ID,
                config=config,
            )
            self.audit_recorder.__enter__()
            self._owns_audit_recorder = True
            if activate_prompt_logging is not None:
                self._prompt_logging_token = activate_prompt_logging(
                    recorder=self.audit_recorder,
                    config=config,
                    module="unified-app-orchestrator",
                    session_id=self.run_id,
                    objective_id=_ORCHESTRATOR_REPORT_OBJECTIVE_ID,
                )
            if RuntimePerformanceTracker is not None:
                self.performance_tracker = RuntimePerformanceTracker(self.audit_recorder)
                self.performance_tracker.sample_resources(
                    label="orchestrator_start",
                    module="unified-app-orchestrator",
                )
            self._audit_event(
                phase="system",
                message="Orchestrator audit recording started",
                data={
                    "session_id": self.run_id,
                    "report_path": str(self._audit_output_dir / self.run_id / _ORCHESTRATOR_REPORT_OBJECTIVE_ID / "report.json"),
                },
                importance=2,
            )
        except Exception as exc:
            logger.warning("Failed to start orchestrator audit recording: %s", exc)
            self.audit_recorder = None
            self._owns_audit_recorder = False

    def _finish_audit_recording(self, caught_error: Exception | None) -> None:
        if self._prompt_logging_token is not None and reset_prompt_logging is not None:
            try:
                reset_prompt_logging(self._prompt_logging_token)
            except Exception as exc:
                logger.warning("Failed to reset prompt logging context: %s", exc)
            finally:
                self._prompt_logging_token = None
        if self.audit_recorder is None or not self._owns_audit_recorder:
            return
        try:
            if self.performance_tracker is not None:
                self.performance_tracker.sample_resources(
                    label="orchestrator_end",
                    module="unified-app-orchestrator",
                )
                self.performance_tracker.finalize()
            if finalize_cost_metrics is not None:
                finalize_cost_metrics(self.audit_recorder)
            self.audit_recorder.__exit__(
                type(caught_error) if caught_error else None,
                caught_error,
                caught_error.__traceback__ if caught_error else None,
            )
        except Exception as exc:
            logger.warning("Failed to close orchestrator audit recorder: %s", exc)

    def _audit_event(
        self,
        *,
        phase: str,
        message: str,
        level: str = "info",
        data: dict[str, Any] | None = None,
        importance: int = 3,
    ) -> None:
        if self.audit_recorder is None:
            return
        try:
            self.audit_recorder.event(
                phase=phase,
                message=message,
                level=level,
                data=data or {},
                importance=importance,
            )
        except Exception as exc:
            logger.warning("Audit event failed (non-fatal): %s", exc)

    def _set_audit_status(self, status: str) -> None:
        if self.audit_recorder is None:
            return
        try:
            self.audit_recorder.report.status = status
        except Exception as exc:
            logger.warning("Failed to update audit status: %s", exc)

    def _update_audit_metrics(self, **metrics: Any) -> None:
        if self.audit_recorder is None:
            return
        try:
            self.audit_recorder.report.metrics.update(metrics)
        except Exception as exc:
            logger.warning("Failed to update audit metrics: %s", exc)

    def _record_backend_execution(
        self,
        objective_index: int,
        objective: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        execution = {
            "objective_index": objective_index,
            "objective_description": objective,
            "backend_module": metadata.get("adapter_name") or metadata.get("module"),
            "flight_report_path": self._derive_backend_report_path(payload),
            "status": payload.get("status"),
        }
        if execution["backend_module"] or execution["flight_report_path"]:
            self._backend_executions.append(execution)
            self._audit_event(
                phase="execution",
                message="Backend execution linked",
                data=execution,
                importance=2,
            )
        return execution

    def _derive_backend_report_path(self, payload: dict[str, Any]) -> str | None:
        if not isinstance(payload, dict):
            return None
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            return None
        explicit_path = metadata.get("flight_report_path")
        if isinstance(explicit_path, str) and explicit_path.strip():
            return explicit_path

        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            raw_path = raw_result.get("flight_report_path")
            if isinstance(raw_path, str) and raw_path.strip():
                return raw_path
            raw_metadata = raw_result.get("metadata", {})
            if isinstance(raw_metadata, dict):
                raw_meta_path = raw_metadata.get("flight_report_path")
                if isinstance(raw_meta_path, str) and raw_meta_path.strip():
                    return raw_meta_path

        session_id = metadata.get("flight_report_session_id")
        objective_id = metadata.get("flight_report_objective_id")
        if isinstance(session_id, str) and session_id.strip() and isinstance(objective_id, str) and objective_id.strip():
            return str(self._audit_output_dir / session_id / objective_id / "report.json")

        if isinstance(raw_result, dict):
            raw_metadata = raw_result.get("metadata", {})
            if isinstance(raw_metadata, dict):
                session_id = raw_metadata.get("flight_report_session_id") or raw_metadata.get("session_id")
                objective_id = raw_metadata.get("flight_report_objective_id") or raw_metadata.get("objective_id")
                if (
                    isinstance(session_id, str) and session_id.strip()
                    and isinstance(objective_id, str) and objective_id.strip()
                ):
                    return str(self._audit_output_dir / session_id / objective_id / "report.json")
        return None

    def _build_snapshot_state(
        self,
        *,
        context: "ExecutionContext",
        objective: str,
        objective_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "objective": objective,
            "objective_index": objective_index,
            "task_description": self.task_description,
            "domain": self.domain,
            "context_summary": context.to_summary(),
            "world_state": context.world_state.to_context_dict(),
            "payload": payload,
        }

    def _write_snapshot_artifact(
        self,
        *,
        name: str,
        snapshot_type: str,
        state: dict[str, Any],
    ) -> str | None:
        if self.audit_recorder is None or write_state_snapshot is None:
            return None
        try:
            return write_state_snapshot(
                self.audit_recorder,
                snapshot_type=snapshot_type,
                state=state,
                name=name,
            )
        except Exception as exc:
            logger.warning("Failed to write state snapshot: %s", exc)
            return None

    def _capture_objective_knowledge_artifacts(
        self,
        *,
        objective: str,
        objective_index: int,
        context: "ExecutionContext",
        payload: dict[str, Any],
        success: bool,
        result_text: str,
        before_snapshot_state: dict[str, Any],
        before_snapshot_path: str | None,
    ) -> None:
        after_snapshot_state = self._build_snapshot_state(
            context=context,
            objective=objective,
            objective_index=objective_index,
            payload=payload,
        )
        after_snapshot_path = self._write_snapshot_artifact(
            name=f"objective_{objective_index}_{'after_success' if success else 'after_failure'}",
            snapshot_type="after_objective",
            state=after_snapshot_state,
        )
        if self.audit_recorder is not None and diff_states is not None:
            try:
                diff_payload = diff_states(before_snapshot_state, after_snapshot_state)
                self._write_snapshot_artifact(
                    name=f"objective_{objective_index}_diff",
                    snapshot_type="state_diff",
                    state=diff_payload,
                )
            except Exception as exc:
                logger.warning("Failed to calculate state diff: %s", exc)

        if self.audit_recorder is None or build_situation_record is None or write_situation_record is None:
            return
        try:
            record = build_situation_record(
                module="unified-app-orchestrator",
                objective=objective,
                domain=self.domain,
                state_summary=f"Objective {objective_index} in {self.domain} with world state {context.world_state.to_context_dict()}",
                constraints=list(context.learned_constraints),
                history=[
                    str(item)
                    for item in context.accumulated_state.keys()
                ],
                decision={
                    "approach": payload.get("metadata", {}).get("adapter_name") or payload.get("status") or "objective_execution",
                    "reasoning": result_text[:200],
                    "alternatives": [],
                    "confidence": 0.9 if success else 0.4,
                },
                outcome={
                    "success": success,
                    "result": result_text[:200],
                    "duration_ms": payload.get("duration_ms") or payload.get("metadata", {}).get("duration_ms"),
                    "issues": [] if success else [result_text[:200]],
                },
                snapshot_ref=after_snapshot_path or before_snapshot_path,
            )
            write_situation_record(
                self.audit_recorder,
                name=f"objective_{objective_index}_situation",
                record=record,
            )
        except Exception as exc:
            logger.warning("Failed to write situation record: %s", exc)


# ── Module helpers ─────────────────────────────────────────────────────────


def _extract_error_core(result_text: str) -> str:
    """Strip [AI error: ...] wrapper to expose the underlying message."""
    if result_text.startswith("[AI error: ") and result_text.endswith("]"):
        return result_text[len("[AI error: "):-1]
    return result_text


def _step_indicates_failure(result_text: str, payload: dict[str, Any]) -> bool:
    if isinstance(result_text, str):
        normalized = result_text.strip()
        if normalized.startswith((
            "ERROR:",
            "[AI error:",
            "[stuck:",
            "[schema error:",
            "[cancelled]",
            "[timeout after",
            "[max iterations",
        )):
            return True

    if not isinstance(payload, dict):
        return False

    status = str(payload.get("status", "")).strip().lower()
    if status == "failure":
        return True

    output = str(payload.get("output", "")).strip().lower()
    if output.startswith("error:"):
        return True

    error = str(payload.get("error", "")).strip().lower()
    if error and error.startswith("error:"):
        return True

    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            raw_status = str(raw_result.get("status", "")).strip().lower()
            if raw_status == "failure":
                return True
            raw_error = str(raw_result.get("error", "")).strip().lower()
            if raw_error and raw_error.startswith("error:"):
                return True

    return False


def _is_missing_resource_failure(result_text: str, payload: dict[str, Any]) -> bool:
    if not _step_indicates_failure(result_text, payload):
        return False

    blob = " ".join(
        part for part in (
            str(result_text or ""),
            _payload_failure_text(payload),
        )
        if part
    )
    return _text_indicates_missing_resource(blob)


def _payload_failure_text(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""

    parts = [
        str(payload.get("output", "") or ""),
        str(payload.get("error", "") or ""),
    ]

    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        parts.append(str(metadata.get("output", "") or ""))
        parts.append(str(metadata.get("text_output", "") or ""))
        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            parts.append(str(raw_result.get("output", "") or ""))
            parts.append(str(raw_result.get("error", "") or ""))

    return " ".join(part for part in parts if part)


def _text_indicates_missing_resource(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return any(
        marker in normalized
        for marker in (
            "not found",
            "does not exist",
            "doesn't exist",
            "could not be found",
            "could not find",
            "couldn't find",
            "unable to locate",
            "not installed",
            "missing",
            "no such",
        )
    )


def _completion_lacks_execution_evidence(objective: str, payload: dict[str, Any]) -> bool:
    if not _objective_requires_execution_evidence(objective):
        return False
    return not _payload_has_execution_evidence(payload)


def _objective_requires_execution_evidence(objective: str) -> bool:
    normalized = re.sub(r"\s+", " ", (objective or "").strip().lower())
    if not normalized:
        return False

    informational_prefixes = (
        "report ",
        "explain ",
        "inform ",
        "notify ",
        "tell the user",
        "summarize ",
        "answer ",
    )
    if normalized.startswith(informational_prefixes):
        return False

    execution_markers = (
        "open ",
        "launch ",
        "start ",
        "search ",
        "go to ",
        "navigate ",
        "click ",
        "type ",
        "paste ",
        "copy ",
        "read ",
        "extract ",
        "capture ",
        "screenshot ",
        "focus ",
        "list ",
        "show ",
        "display ",
        "find ",
        "run ",
        "execute ",
        "rename ",
        "move ",
        "delete ",
        "close ",
        "use cli",
        "use the cli",
        "use browser",
        "use the browser",
        "use desktop",
        "use the desktop",
    )
    return any(marker in normalized for marker in execution_markers)


def _payload_has_execution_evidence(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False

    status = str(payload.get("status", "")).strip().lower()
    if status == "failure":
        return False

    if payload.get("execution_log") or payload.get("artifacts"):
        return True

    if _is_meaningful_payload_text(payload.get("output")):
        return True

    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        if _is_meaningful_payload_text(metadata.get("text_output")):
            return True
        if _is_meaningful_payload_text(metadata.get("output")):
            return True

        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            raw_status = str(raw_result.get("status", "")).strip().lower()
            if raw_status == "failure":
                return False
            if raw_result.get("execution_log") or raw_result.get("artifacts"):
                return True
            if _is_meaningful_payload_text(raw_result.get("output")):
                return True

            raw_metadata = raw_result.get("metadata", {})
            if isinstance(raw_metadata, dict):
                if _is_meaningful_payload_text(raw_metadata.get("text_output")):
                    return True
                if _is_meaningful_payload_text(raw_metadata.get("output")):
                    return True

    return False


def _is_meaningful_payload_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith((
        "ERROR:",
        "OK (status=",
        "OK (no output)",
        "Navigated",
        "Opened",
        "Focused",
        "Clicked",
        "Typed",
        "Pasted",
        "Closed",
    )):
        return False
    return True


def _counts_toward_task_completion(objective: str) -> bool:
    """Exclude pure failure-reporting steps from overall task success math."""
    return not _is_failure_report_objective(objective)


def _is_failure_report_objective(objective: str) -> bool:
    normalized = re.sub(r"\s+", " ", (objective or "").strip().lower())
    if not normalized.startswith(_FAILURE_REPORT_PREFIXES):
        return False
    return any(marker in normalized for marker in _FAILURE_REPORT_MARKERS)
