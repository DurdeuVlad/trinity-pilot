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

import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .agent_loop import AgentLoop
from .checkpoint_manager import CheckpointManager
from .database import TaskStatus
from .execution_context import ErrorRecord, ExecutionContext
from .macro_planner import ExecutionPlan
from .output_validator import OutputValidator
from .prompt_registry import PromptRegistry
from .reflection_engine import ReflectionEngine

if TYPE_CHECKING:
    from .providers.base import LLMProvider

MAX_ATTEMPTS_PER_OBJECTIVE = 3
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
_MISSING_RESOURCE_MARKERS = (
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
        approved_plan: list[str] | None = None,
        provider_name: str = "gemini",
        timeout_seconds: int = 600,
        max_retries: int = 3,
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
        self.approved_plan = [step.strip() for step in (approved_plan or []) if step.strip()]
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

        self.registry = PromptRegistry(provider_name)
        self.checkpoint_manager = CheckpointManager()  # uses absolute default path
        self.output_validator = OutputValidator()
        self.reflection_engine = ReflectionEngine(provider, self.registry)

    async def execute(self) -> None:
        """Run the full orchestration lifecycle."""
        try:
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

            # ── Plan ───────────────────────────────────────────────────────
            if self.approved_plan:
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
                    plan = await self.planner.generate_plan(self.task_description, self.domain)
                except Exception as plan_exc:
                    self._handle_plan_failure(plan_exc)
                    return

            if hasattr(self.history_manager, "update_task_plan"):
                self.history_manager.update_task_plan(
                    self.run_id,
                    plan_steps=plan.steps,
                    estimated_duration=plan.estimated_duration,
                    confidence=plan.confidence,
                )
            self._signal("plan_generated", plan.steps)
            n = len(plan.steps)
            self._status("Starting execution...", "info")
            self._status(f"Got it — I'll tackle this in {n} step{'s' if n != 1 else ''}.", "success")

            # ── Checkpoint resume ──────────────────────────────────────────
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
            )

            # Live list — replan may shrink/reshape the tail
            objectives: list[str] = list(plan.steps)
            completed: list[tuple[int, str]] = []
            failed: list[tuple[int, str, str]] = []

            index = 0
            while index < len(objectives):
                objective = objectives[index]
                display_index = index + 1  # 1-based for UI

                if display_index <= start_index:
                    completed.append((display_index, objective))
                    index += 1
                    continue

                if self.cancel_requested():
                    self._complete_as_cancelled()
                    return

                self.history_manager.add_step(self.run_id, display_index, objective)
                self._signal("step_started", display_index, objective)
                self._status(
                    f"Executing objective {display_index} of {len(objectives)}...",
                    "info",
                )
                self._status(
                    f"{display_index}/{len(objectives)}|{objective}", "step"
                )
                self.history_manager.update_step_status(
                    self.run_id, display_index, TaskStatus.RUNNING
                )

                # ── Act → Reflect loop ─────────────────────────────────────
                objective_achieved = False
                final_result = ""
                critique = ""

                for attempt in range(MAX_ATTEMPTS_PER_OBJECTIVE):
                    if self.cancel_requested():
                        await agent_loop.cleanup_browser_session(display_index, context)
                        self._complete_as_cancelled(active_step=display_index)
                        return

                    if attempt > 0:
                        self._status(
                            f"Retrying objective {display_index} with a different approach...",
                            "thinking",
                        )
                        self._status(
                            "Hmm, that didn't quite work. Let me try a different approach…",
                            "thinking",
                        )

                    # ACT
                    result = await agent_loop.act(
                        objective=objective,
                        obj_index=display_index,
                        context=context,
                        adapt_hint=critique,
                    )

                    if result == "[cancelled]":
                        await agent_loop.cleanup_browser_session(display_index, context)
                        self._complete_as_cancelled(active_step=display_index)
                        return

                    final_result = result

                    # REFLECT
                    reflection = await self.reflection_engine.reflect(
                        objective=objective,
                        result=result,
                        attempt=attempt,
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

                    if (
                        _is_missing_resource_failure(final_result, step_payload)
                        or _text_indicates_missing_resource(reflection.critique)
                    ):
                        critique = (
                            "The required target could not be found. Stop retrying alternate execution paths and "
                            "replan the remaining objectives around this failure."
                        )
                        self._status(
                            "The required target could not be found. Moving to failure handling...",
                            "warning",
                        )
                        if hasattr(self.provider, "report_cache_failure"):
                            self.provider.report_cache_failure()
                        context.add_error(ErrorRecord(
                            error_type="missing_resource_failure",
                            error_message=critique,
                            attempted_action={"objective": objective, "attempt": attempt},
                            timestamp=time.time(),
                        ))
                        break

                    # Not achieved — prepare critique for next attempt
                    critique = (
                        reflection.critique
                        or "The previous attempt did not fully achieve the objective. Try a different approach."
                    )
                    self._status(
                        "That attempt didn't fully achieve the goal. Retrying…",
                        "warning",
                    )
                    self._status(
                        f"Objective {display_index} is not complete yet. Retrying...",
                        "warning",
                    )
                    # Notify the cache that the most recent cached response may
                    # have contributed to this failure so it can evict the entry
                    # after BYPASS_THRESHOLD failures.
                    if hasattr(self.provider, "report_cache_failure"):
                        self.provider.report_cache_failure()
                    context.add_error(ErrorRecord(
                        error_type="reflection_failure",
                        error_message=critique,
                        attempted_action={"objective": objective, "attempt": attempt},
                        timestamp=time.time(),
                    ))

                # ── Outcome ────────────────────────────────────────────────
                step_payload = dict(agent_loop.last_step_payload or {})
                if objective_achieved and _step_indicates_failure(final_result, step_payload):
                    objective_achieved = False

                if objective_achieved:
                    completed.append((display_index, objective))
                    # Persist objective result into shared context so subsequent
                    # objectives know what has already been accomplished and what
                    # state the world is in (e.g. which app is open, which file
                    # was created, which URL was navigated to).
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
                    self._signal("step_completed", display_index, payload)
                    # agent_loop already emitted the result_summary as a green
                    # success line — no extra _status() needed here to avoid duplicates.
                    self.history_manager.update_step_status(
                        self.run_id, display_index, TaskStatus.COMPLETED, result_data=payload
                    )

                else:
                    # All attempts exhausted — try to replan the remaining tail
                    failed.append((display_index, objective, final_result))
                    self._signal("step_failed", display_index, final_result)
                    self._status(
                        "Couldn't complete this step after multiple attempts. Moving on…",
                        "warning",
                    )
                    self.history_manager.update_step_status(
                        self.run_id, display_index, TaskStatus.FAILED,
                        error_message=final_result,
                    )

                    remaining_tail = objectives[index + 1:]
                    if remaining_tail:
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

                index += 1

            await agent_loop.cleanup_browser_session(0, context)

            # ── Cleanup & final status ─────────────────────────────────────
            try:
                self.checkpoint_manager.delete_task_checkpoints(self.run_id)
            except Exception:
                pass

            total = len(objectives)
            effective_total = max(
                1,
                sum(1 for objective in objectives if _counts_toward_task_completion(objective)),
            )
            total = effective_total
            n_done = sum(1 for _, objective in completed if _counts_toward_task_completion(objective))
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
                msg = f"Partially done — completed {n_done} of {total} steps."
                error_message = msg

            self._signal("execution_complete", {"status": status, "category": category})
            if status == "success":
                self._status("Execution completed successfully.", "success")
            level = "done" if status == "success" else ("fail" if status == "failure" else "warning")
            self._status(msg, level)

            # Post result summary back to chat
            if status == "success":
                chat_msg = f"Done! Task completed: {self.task_description}"
                if n_done > 1:
                    chat_msg += f" ({n_done} steps completed)"
            elif status == "partial":
                chat_msg = f"Partially done — {n_done} of {total} steps succeeded."
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

        finally:
            agent_loop_obj = locals().get("agent_loop")
            context_obj = locals().get("context")
            if agent_loop_obj is not None:
                try:
                    await agent_loop_obj.cleanup_browser_session(0, context_obj)
                except Exception:
                    pass
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
            return revised if revised is not None else remaining
        except Exception as exc:
            self._status("Couldn't revise the plan — continuing with what I have.", "warning")
            return remaining

    # ── Plan failure ───────────────────────────────────────────────────────

    def _handle_plan_failure(self, exc: Exception) -> None:
        error_payload = self.error_handler.handle(exc, context="Plan generation")
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
        self._status("Stopped — cancelled by you.", "warning")
        self._signal("execution_complete", {"status": "cancelled", "category": "cancelled"})
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

    def _signal(self, name: str, *args: Any) -> None:
        try:
            getattr(self.event_bus, name).emit(*args)
        except RuntimeError:
            pass

    def _status(self, message: str, level: str) -> None:
        try:
            self.event_bus.emit_status(message, level)
        except RuntimeError:
            pass


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
    return any(marker in normalized for marker in _MISSING_RESOURCE_MARKERS)


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
