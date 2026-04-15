"""
Active Reviewer - Coaches the executor instead of just judging.

The reviewer provides actionable feedback to help the executor complete objectives.
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class ReviewStatus(Enum):
    """Review status options."""

    SUCCESS = "success"  # Objective fully complete
    CONTINUE = "continue"  # Partial progress, needs more work
    PIVOT = "pivot"  # Stuck, needs different approach
    FAILED = "failed"  # Exhausted all options


@dataclass
class ReviewResult:
    """Result of reviewing executor progress."""

    status: ReviewStatus
    assessment: str
    missing: List[str]
    next_steps: List[str]
    hints: List[str]
    alternative_strategies: List[str]
    confidence: float


class ActiveReviewer:
    """
    Active reviewer that coaches the executor.

    Instead of just marking tasks as failed, provides specific guidance
    on what's missing and how to complete the objective.
    """

    def __init__(self, llm_provider):
        self.llm = llm_provider
        self.logger = logging.getLogger(__name__)

    async def review_progress(
        self,
        objective: str,
        completed_tasks: List[Dict],
        world_state: Dict,
        attempt: int,
        max_attempts: int = 5,
        execution_log: Optional[List[Dict]] = None,
        error_history: Optional[List[Dict]] = None,
        plan_state: Optional[Dict] = None,
        verification: Optional[Dict] = None,
    ) -> ReviewResult:
        """
        Review executor progress and provide actionable feedback.

        Args:
            objective: The original objective to complete
            completed_tasks: Module-level results so far
            world_state: Current world state (use WorldState.to_context_dict())
            attempt: Current attempt number (0-indexed)
            max_attempts: Maximum attempts allowed
            execution_log: Per-turn tool results from the last agent loop run
            error_history: Error records from the execution context

        Returns:
            ReviewResult with status and guidance
        """
        self.logger.info("[ActiveReviewer] Reviewing progress (attempt %s/%s)", attempt + 1, max_attempts)

        prompt = self._build_review_prompt(
            objective,
            completed_tasks,
            world_state,
            attempt,
            max_attempts,
            execution_log or [],
            error_history or [],
            plan_state or {},
            verification or {},
        )

        try:
            messages = [
                {
                    "role": "user",
                    "content": (
                        prompt
                        + "\n\nRespond in JSON format with: status, assessment, missing, "
                        "next_steps, hints, alternative_strategies, confidence"
                    ),
                }
            ]
            response = await self.llm.call(messages, json_mode=True, purpose="review")

            import json
            import re

            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                else:
                    raise

            return self._parse_review(parsed)

        except Exception as exc:
            self.logger.error("[ActiveReviewer] Review failed: %s", exc)
            if attempt >= max_attempts - 1:
                return ReviewResult(
                    status=ReviewStatus.FAILED,
                    assessment=f"Unable to assess progress after {attempt + 1} attempts (reviewer error: {exc})",
                    missing=["Unknown"],
                    next_steps=[],
                    hints=[],
                    alternative_strategies=[],
                    confidence=0.3,
                )
            return ReviewResult(
                status=ReviewStatus.CONTINUE,
                assessment="Unable to assess progress",
                missing=["Unknown"],
                next_steps=["Continue with current approach"],
                hints=[],
                alternative_strategies=[],
                confidence=0.5,
            )

    def _build_review_prompt(
        self,
        objective: str,
        completed_tasks: List[Dict],
        world_state: Dict,
        attempt: int,
        max_attempts: int,
        execution_log: List[Dict],
        error_history: List[Dict],
        plan_state: Dict,
        verification: Dict,
    ) -> str:
        """Build the review prompt for the LLM."""
        tasks_summary = self._format_tasks(completed_tasks)
        state_summary = self._format_world_state(world_state)
        log_summary = self._format_execution_log(execution_log)
        errors_summary = self._format_error_history(error_history)
        plan_state_summary = self._format_plan_state(plan_state)
        verification_summary = self._format_verification(verification)

        return f"""You are a coach reviewing an AI agent's progress on a task.

ORIGINAL OBJECTIVE:
{objective}

ATTEMPT: {attempt + 1}/{max_attempts}

EXECUTION LOG (what the agent actually ran this attempt):
{log_summary}

ERROR HISTORY (failures across all attempts so far):
{errors_summary}

CURRENT LOW-LEVEL PLAN STATE:
{plan_state_summary}

DETERMINISTIC VERIFICATION:
{verification_summary}

MODULE RESULTS (last result per backend):
{tasks_summary}

CURRENT WORLD STATE:
{state_summary}

Your job is to:
1. Assess if the objective is FULLY complete (all parts of the original request)
2. If not complete, identify EXACTLY what's missing
3. Provide SPECIFIC, actionable next steps (not vague suggestions)
4. Give helpful hints to overcome obstacles
5. Suggest alternative approaches if the agent is stuck

Guidelines:
- The deterministic verification layer already evaluated structured postconditions. Treat it as the primary source of truth.
- If deterministic verification status is FAILURE, do not mark SUCCESS. Your job is only to coach the next attempt.
- If deterministic verification status is UNKNOWN, use the failed or unknown checks and evidence summary to decide whether to CONTINUE, PIVOT, or FAIL.
- If the execution log shows repeated identical errors, mark as PIVOT or FAILED, not CONTINUE.
- If the same error appears more than twice in error history, suggest a different approach.
- Only mark SUCCESS if there is concrete execution evidence the objective was completed.
- Only mark FAILED if truly impossible after {max_attempts} attempts.
- Treat loading, startup, rendering, or attachment delays as transient. If the app, page, or window may still be appearing, prefer CONTINUE with explicit wait or retry guidance.
- Errors like window_not_found, selector not found, or element not visible are not automatically permanent if the target was just launched, navigated, or refreshed.
- If the low-level plan still has pending or in-progress work, do not mark FAILED unless there is strong evidence the target is truly unavailable.
- If the low-level plan shows blocked work because the target is still loading or attaching, prefer CONTINUE with a wait-and-recheck instruction.
- If you are unsure whether the target finished loading, prefer CONTINUE over FAILED.

Respond with your assessment and guidance."""

    def _format_tasks(self, tasks: List[Dict]) -> str:
        """Format completed tasks for review."""
        if not tasks:
            return "No tasks completed yet"

        lines = []
        for i, task in enumerate(tasks, 1):
            status = task.get("status", "unknown")
            desc = task.get("description", "Unknown task")
            result = task.get("result", "")

            status_marker = "[ok]" if status == "success" else "[x]"
            lines.append(f"{i}. {status_marker} {desc}")
            if result:
                lines.append(f"   Result: {result[:100]}...")

        return "\n".join(lines)

    def _format_world_state(self, world_state: Dict) -> str:
        """Format world state for review."""
        if not world_state:
            return "No state information available"

        lines = [f"- {k}: {v}" for k, v in world_state.items() if v]
        return "\n".join(lines) if lines else "No relevant state"

    def _format_execution_log(self, execution_log: List[Dict]) -> str:
        if not execution_log:
            return "No execution log available"

        lines = []
        for entry in execution_log:
            action = entry.get("action") or entry.get("step") or "?"
            result = entry.get("result") or entry.get("details") or ""
            status = entry.get("status") or ("error" if str(result).startswith("ERROR") else "ok")
            lines.append(f"  [{status}] {str(action)[:120]} -> {str(result)[:150]}")
        return "\n".join(lines)

    def _format_error_history(self, error_history: List[Dict]) -> str:
        if not error_history:
            return "No errors recorded"

        lines = []
        for err in error_history:
            etype = err.get("type", "error")
            msg = err.get("message", "")
            lines.append(f"  [{etype}] {str(msg)[:200]}")
        return "\n".join(lines)

    def _format_plan_state(self, plan_state: Dict) -> str:
        if not isinstance(plan_state, dict) or not plan_state:
            return "No plan state available"

        steps = plan_state.get("steps") or []
        if not isinstance(steps, list):
            steps = []

        summary_bits: List[str] = []
        revision = plan_state.get("revision") or plan_state.get("version")
        if revision is not None:
            summary_bits.append(f"revision={revision}")
        active_index = plan_state.get("active_step_index")
        if active_index is None:
            active_index = plan_state.get("currentStepIndex")
        if active_index is not None:
            summary_bits.append(f"active_step={active_index}")

        lines = [", ".join(summary_bits) if summary_bits else "Plan metadata unavailable"]
        for idx, step in enumerate(steps[:8], start=1):
            if not isinstance(step, dict):
                continue
            status = step.get("status", "unknown")
            label = (
                step.get("title")
                or step.get("command")
                or step.get("action")
                or step.get("expectedResult")
                or f"step {idx}"
            )
            lines.append(f"  [{status}] {str(label)[:160]}")
        return "\n".join(lines)

    def _format_verification(self, verification: Dict) -> str:
        if not isinstance(verification, dict) or not verification:
            return "No deterministic verification available"

        status = str(verification.get("status", "unknown") or "unknown").strip()
        summary = str(verification.get("summary", "") or "").strip()
        checks = verification.get("checks") or []
        lines = [f"status={status}"]
        if summary:
            lines.append(f"summary={summary}")
        for check in checks[:6]:
            if not isinstance(check, dict):
                continue
            check_status = str(check.get("status", "unknown") or "unknown").strip()
            kind = str(check.get("kind", "check") or "check").strip()
            message = str(check.get("message", "") or "").strip()
            lines.append(f"[{check_status}] {kind}: {message}")
        return "\n".join(lines)

    def _parse_review(self, response: Dict) -> ReviewResult:
        """Parse LLM response into ReviewResult."""

        status_str = str(response.get("status", "continue") or "continue").strip().lower()
        try:
            status = ReviewStatus(status_str)
        except ValueError:
            status = ReviewStatus.CONTINUE

        return ReviewResult(
            status=status,
            assessment=str(response.get("assessment", "") or ""),
            missing=self._coerce_list(response.get("missing")),
            next_steps=self._coerce_list(response.get("next_steps")),
            hints=self._coerce_list(response.get("hints")),
            alternative_strategies=self._coerce_list(response.get("alternative_strategies")),
            confidence=self._coerce_confidence(response.get("confidence", 0.5)),
        )

    @staticmethod
    def _coerce_list(value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @staticmethod
    def _coerce_confidence(value) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, confidence))

    def format_feedback_for_executor(self, review: ReviewResult) -> str:
        """Format review feedback for injection into executor context."""

        lines = [
            "=== REVIEWER FEEDBACK ===",
            f"Status: {review.status.value.upper()}",
            f"Assessment: {review.assessment}",
        ]

        if review.missing:
            lines.append("\nWhat's Missing:")
            for item in review.missing:
                lines.append(f"  [x] {item}")

        if review.next_steps:
            lines.append("\nNext Steps:")
            for i, step in enumerate(review.next_steps, 1):
                lines.append(f"  {i}. {step}")

        if review.hints:
            lines.append("\nHints:")
            for hint in review.hints:
                lines.append(f"  [hint] {hint}")

        if review.alternative_strategies:
            lines.append("\nAlternative Approaches:")
            for strategy in review.alternative_strategies:
                lines.append(f"  [pivot] {strategy}")

        lines.append("=" * 50)

        return "\n".join(lines)
