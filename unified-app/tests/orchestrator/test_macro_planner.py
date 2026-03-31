"""Tests for the MacroPlanner and its dataclass contract."""
from __future__ import annotations

import json

import pytest

from orchestrator.macro_planner import ExecutionPlan, MacroPlanner, PlanStep


class FakeProvider:
    """Instant-done fake provider for planner unit tests."""

    def __init__(self, objectives: list[str] | None = None) -> None:
        self._objectives = objectives or ["step one", "step two"]

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        return json.dumps({"objectives": self._objectives})

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


# ── ExecutionPlan dataclass ────────────────────────────────────────────────

def test_execution_plan_auto_builds_structured_steps_from_strings() -> None:
    plan = ExecutionPlan(
        description="demo",
        domain="cli",
        steps=["step a", "step b"],
        estimated_duration=10,
        confidence=0.8,
    )

    assert len(plan.structured_steps) == 2
    assert plan.structured_steps[0] == PlanStep(description="step a", domain="cli")
    assert plan.structured_steps[1] == PlanStep(description="step b", domain="cli")


def test_execution_plan_syncs_steps_from_structured_steps() -> None:
    structured = [
        PlanStep(description="navigate", domain="web", expected_outcome="page loaded"),
        PlanStep(description="click", domain="web"),
    ]
    plan = ExecutionPlan(
        description="web demo",
        domain="web",
        steps=[],
        estimated_duration=20,
        confidence=0.9,
        structured_steps=structured,
    )

    assert plan.steps == ["navigate", "click"]


# ── MacroPlanner ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_macro_planner_returns_execution_plan() -> None:
    planner = MacroPlanner(FakeProvider(["Open Notepad", "Type text"]))
    plan = await planner.generate_plan("Write a note", "desktop")

    assert isinstance(plan, ExecutionPlan)
    assert plan.steps == ["Open Notepad", "Type text"]
    assert plan.domain == "desktop"
    assert plan.description == "Write a note"
    assert plan.confidence == 0.9


@pytest.mark.asyncio
async def test_macro_planner_falls_back_to_task_description_on_provider_error() -> None:
    class FailingProvider:
        async def call(self, messages, *, json_mode=True):
            raise RuntimeError("API down")

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    planner = MacroPlanner(FailingProvider())
    plan = await planner.generate_plan("List Python files", "cli")

    assert plan.steps == ["List Python files"]
    assert plan.domain == "cli"


@pytest.mark.asyncio
async def test_macro_planner_estimated_duration_scales_with_objective_count() -> None:
    planner = MacroPlanner(FakeProvider(["obj1", "obj2", "obj3"]))
    plan = await planner.generate_plan("Three-objective task", "web")

    assert plan.estimated_duration == 3 * 60


@pytest.mark.asyncio
async def test_macro_planner_single_objective_falls_back_to_task_description_on_empty() -> None:
    class EmptyProvider:
        async def call(self, messages, *, json_mode=True):
            return json.dumps({"objectives": []})

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    planner = MacroPlanner(EmptyProvider())
    plan = await planner.generate_plan("Simple task", "cli")

    assert plan.steps == ["Simple task"]
