from __future__ import annotations

from temporalio import activity


@activity.defn
async def plan_objectives(user_request: str) -> list[dict]:
    """Decompose user request into ObjectiveSpec dicts. Implemented in Pass 2."""
    raise NotImplementedError("Planner not implemented — Pass 2")


@activity.defn
async def execute_objective(spec_dict: dict) -> dict:
    """Execute a single objective via the appropriate domain worker. Implemented in Pass 3."""
    raise NotImplementedError("Domain workers not implemented — Pass 3")


@activity.defn
async def review_objective(spec_dict: dict, evidence: dict) -> dict:
    """Review objective execution against acceptance criteria. Implemented in Pass 2."""
    raise NotImplementedError("Reviewer not implemented — Pass 2")
