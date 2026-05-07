from __future__ import annotations

import os
from typing import Any

from temporalio import activity

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer


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
    """Execute a single objective via domain worker. Implemented in Pass 3."""
    raise NotImplementedError("Domain workers not implemented — Pass 3")


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
    }
