"""Macro planner — decomposes user goals into objectives and replans on failure."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .providers.base import LLMProvider
    from .prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

_MISSING_RESOURCE_MARKERS = (
    "not found",
    "does not exist",
    "doesn't exist",
    "could not find",
    "couldn't find",
    "unable to locate",
    "not installed",
    "missing",
    "no such",
)


@dataclass(eq=True, frozen=True)
class PlanStep:
    """One executable objective with its domain hint."""

    description: str
    domain: str
    expected_outcome: Optional[str] = None


@dataclass
class ExecutionPlan:
    """Structured plan produced by the macro planner."""

    description: str
    domain: str
    steps: list[str]
    estimated_duration: int
    confidence: float
    structured_steps: list[PlanStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.structured_steps:
            self.steps = [s.description for s in self.structured_steps]
            return
        self.structured_steps = [
            PlanStep(description=s, domain=self.domain) for s in self.steps
        ]


class MacroPlanner:
    """Decompose user tasks into objectives; replan when objectives fail mid-run."""

    def __init__(self, provider: "LLMProvider", registry: Optional["PromptRegistry"] = None) -> None:
        self._provider = provider
        self._registry = registry

    async def generate_plan(
        self, task_description: str, domain: str, capabilities: dict | None = None
    ) -> ExecutionPlan:
        """Decompose the task into objectives and return an ExecutionPlan."""
        from .objectives_decomposer import ObjectivesDecomposer

        decomposer = ObjectivesDecomposer(self._provider, registry=self._registry)
        objectives = await decomposer.decompose(task_description, capabilities=capabilities)
        steps = objectives or [task_description]
        return ExecutionPlan(
            description=task_description,
            domain=domain,
            steps=steps,
            estimated_duration=len(steps) * 60,
            confidence=0.9,
        )

    async def replan(
        self,
        original_task: str,
        completed: list[str],
        failed: list[tuple[str, str]],   # [(objective, failure_reason), ...]
        remaining: list[str],
        constraints: list[str] | None = None,
    ) -> list[str]:
        """Generate a revised list of remaining objectives after one or more failures.

        Returns the revised objective list, or the original *remaining* list if
        the LLM call fails or produces nothing useful.
        """
        if not remaining:
            return []
        if _failed_due_to_missing_resource(failed):
            return [_build_missing_resource_report_objective(bool(completed))]

        completed_block = (
            "\n".join(f"  ✓ {obj}" for obj in completed) if completed else "  (none)"
        )
        failed_block = "\n".join(
            f"  ✗ {obj} — reason: {reason[:120]}" for obj, reason in failed
        )
        remaining_block = "\n".join(f"  • {obj}" for obj in remaining)

        constraints_block = ""
        if constraints:
            constraints_block = (
                "\n\nKNOWN CONSTRAINTS (approaches that have already failed — do NOT repeat these):\n"
                + "\n".join(f"  ⚠ {c}" for c in constraints[:10])
            )

        system_prompt = self._replan_system_prompt()
        user_content = (
            f"ORIGINAL TASK: {original_task}\n\n"
            f"COMPLETED OBJECTIVES:\n{completed_block}\n\n"
            f"FAILED OBJECTIVES:\n{failed_block}\n\n"
            f"REMAINING OBJECTIVES (not yet attempted):\n{remaining_block}"
            f"{constraints_block}\n\n"
            "Generate a revised list of remaining objectives."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        try:
            raw = await self._provider.call(messages, json_mode=True)
            data = _parse_json(raw)
            revised = data.get("revised_objectives", [])
            if isinstance(revised, list) and revised:
                rationale = data.get("rationale", "")
                logger.info(
                    "[MacroPlanner.replan] %d → %d objectives. rationale=%s",
                    len(remaining),
                    len(revised),
                    rationale[:80],
                )
                return [str(obj).strip() for obj in revised if str(obj).strip()]
        except Exception as exc:
            logger.warning("[MacroPlanner.replan] Failed (%s) — keeping original plan", exc)

        return remaining

    def _replan_system_prompt(self) -> str:
        if self._registry is not None:
            return self._registry.replan_system_prompt()
        # Fallback if no registry supplied (e.g., tests)
        return (
            "You are a task planning assistant. Some objectives failed mid-execution. "
            "Generate a revised list of remaining objectives.\n"
            'Respond ONLY with JSON: {"revised_objectives": [...], "rationale": "..."}'
        )


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Cannot parse planner JSON: {raw[:200]}")


def _failed_due_to_missing_resource(failed: list[tuple[str, str]]) -> bool:
    for _objective, reason in failed:
        normalized = str(reason or "").strip().lower()
        if any(marker in normalized for marker in _MISSING_RESOURCE_MARKERS):
            return True
    return False


def _build_missing_resource_report_objective(has_completed_steps: bool) -> str:
    if has_completed_steps:
        return (
            "Tell the user that the required target could not be found, so the remaining steps "
            "cannot be completed."
        )
    return (
        "Tell the user that the required target could not be found, so the task cannot be completed."
    )
