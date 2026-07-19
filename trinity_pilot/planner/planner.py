from __future__ import annotations

import json
import re

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.llm.base import LLMMessage, LLMProvider
from trinity_pilot.planner.dag import infer_cross_domain_independence, resolve_execution_order
from trinity_pilot.planner.prompts import PLANNER_SYSTEM, PLANNER_USER_TEMPLATE


class PlanningError(Exception):
    pass


def _extract_json(text: str) -> str:
    """Strip markdown code fences and fix common LLM JSON artifacts."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ``` (including partial closing fence)
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*(?:```|$)", text)
    if match:
        text = match.group(1).strip()
    # Remove trailing commas before ] or } (common LLM mistake)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


class ObjectivePlanner:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def plan(self, user_request: str) -> list[ObjectiveSpec]:
        import time as _time

        from trinity_pilot.telemetry.trace import emit

        t0 = _time.monotonic()
        user_msg = PLANNER_USER_TEMPLATE.format(user_request=user_request)
        messages = [LLMMessage(role="user", content=user_msg)]

        emit(
            "planner.py:plan",
            "llm_call_start",
            {"request_preview": user_request[:120]},
        )
        try:
            response = await self._provider.complete(
                messages=messages,
                system=PLANNER_SYSTEM,
            )
            emit(
                "planner.py:plan",
                "llm_call_done",
                {
                    "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                    "response_len": len(response.content or ""),
                },
            )
        except Exception as exc:
            emit(
                "planner.py:plan",
                "llm_call_failed",
                {
                    "elapsed_ms": int((_time.monotonic() - t0) * 1000),
                    "error": str(exc)[:500],
                },
            )
            raise PlanningError(f"LLM call failed: {exc}") from exc

        raw = _extract_json(response.content)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            context = user_request[:100]
            raise PlanningError(
                f"Planner returned invalid JSON: {exc}"
                f"\nRequest context: {context!r}"
                f"\nRaw response:\n{response.content}"
            ) from exc

        if not isinstance(data, list):
            raise PlanningError(
                f"Planner must return a JSON array, got: {type(data).__name__}"
            )

        specs: list[ObjectiveSpec] = []
        for i, item in enumerate(data):
            try:
                spec = ObjectiveSpec.from_dict(item)
            except (KeyError, ValueError, TypeError) as exc:
                raise PlanningError(
                    f"Objective at index {i} failed to parse: {exc}\nData: {item}"
                ) from exc
            try:
                spec.validate()
            except ValueError as exc:
                raise PlanningError(
                    f"Objective '{spec.objective_id}' failed validation: {exc}"
                ) from exc
            specs.append(spec)

        if not specs:
            raise PlanningError("Planner returned an empty plan.")

        try:
            ordered = resolve_execution_order(specs)
        except Exception as exc:
            raise PlanningError(f"Dependency resolution failed: {exc}") from exc

        return infer_cross_domain_independence(ordered)
