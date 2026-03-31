"""Tests for the objectives-based MacroPlanner with a fake provider."""
from __future__ import annotations

import json

import pytest

from orchestrator.macro_planner import ExecutionPlan, MacroPlanner


class FakeProvider:
    """Fake LLMProvider that returns a fixed objectives JSON response."""

    def __init__(self, response: str | None = None) -> None:
        self._response = response or json.dumps(
            {"objectives": ["Open Notepad", "Type text", "Save file"]}
        )
        self.calls: list[list[dict]] = []

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        self.calls.append(messages)
        return self._response

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


@pytest.mark.asyncio
async def test_generate_plan_returns_objectives_as_steps() -> None:
    provider = FakeProvider()
    planner = MacroPlanner(provider)
    plan = await planner.generate_plan("Write a note in Notepad", "desktop")

    assert isinstance(plan, ExecutionPlan)
    assert plan.steps == ["Open Notepad", "Type text"]
    assert plan.estimated_duration == 120
    assert plan.confidence == 0.9
    assert plan.domain == "desktop"
    assert plan.description == "Write a note in Notepad"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_generate_plan_falls_back_when_provider_returns_invalid_json() -> None:
    provider = FakeProvider(response="not valid json at all")
    planner = MacroPlanner(provider)
    plan = await planner.generate_plan("List Python files", "cli")

    assert plan.steps == ["List Python files"]
    assert plan.domain == "cli"


@pytest.mark.asyncio
async def test_generate_plan_falls_back_when_provider_raises() -> None:
    class ErrorProvider:
        async def call(self, messages, *, json_mode=True):
            raise RuntimeError("network failure")

        async def probe(self):
            pass

        @property
        def provider_name(self):
            return "fake"

    planner = MacroPlanner(ErrorProvider())
    plan = await planner.generate_plan("Do something", "web")

    assert plan.steps == ["Do something"]


@pytest.mark.asyncio
async def test_generate_plan_task_description_is_passed_to_provider() -> None:
    provider = FakeProvider()
    planner = MacroPlanner(provider)
    await planner.generate_plan("Search Wikipedia for cats", "web")

    sent_messages = provider.calls[0]
    all_content = " ".join(m["content"] for m in sent_messages if isinstance(m.get("content"), str))
    assert "Search Wikipedia for cats" in all_content


@pytest.mark.asyncio
async def test_generate_plan_strips_unrequested_save_objective() -> None:
    provider = FakeProvider(
        response=json.dumps(
            {
                "objectives": [
                    "Find the installed Python version using the command line.",
                    "Open Notepad.",
                    "Write the Python version number into the Notepad window.",
                    "Save the Notepad file.",
                ]
            }
        )
    )
    planner = MacroPlanner(provider)

    plan = await planner.generate_plan(
        "Use CLI to find the Python version installed on this system, then open Notepad and write the version number into it",
        "mixed",
    )

    assert plan.steps == [
        "Find the installed Python version using the command line.",
        "Open Notepad.",
        "Write the Python version number into the Notepad window.",
    ]


@pytest.mark.asyncio
async def test_generate_plan_preserves_explicit_save_objective() -> None:
    provider = FakeProvider(
        response=json.dumps(
            {
                "objectives": [
                    "Open Notepad.",
                    "Write the Python version number into the Notepad window.",
                    "Save the Notepad file.",
                ]
            }
        )
    )
    planner = MacroPlanner(provider)

    plan = await planner.generate_plan(
        "Open Notepad, write the Python version number into it, and save the Notepad file.",
        "mixed",
    )

    assert plan.steps[-1] == "Save the Notepad file."
