from __future__ import annotations

import sys
from pathlib import Path

import pytest

from trinity_core.config import TrinityConfig
from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.models import ObjectiveEvidence, ObjectivePlan, SubObjective, SubObjectiveResult, TaskInput
from trinity_core.objective_planner import ObjectivePlanner
from trinity_core.strategy_registry import MCPStrategy, StrategyRegistry
from trinity_core.trinity import ObjectiveOrchestrator


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if tools and self.calls % 2 == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="inspect_state", arguments={})])
        return LLMResponse(text="done")


class _ShrinkingPlanLLM:
    async def call(self, messages, tools):
        return LLMResponse(
            text="""
            {
              "objective_id": "desktop-template",
              "objective": "Create a meeting notes template",
              "strategy": "finish_objective",
              "sub_objectives": [
                {
                  "sub_objective_id": "sub-1",
                  "objective": "Open Notepad",
                  "domain": "desktop",
                  "target_server": "fake_desktop",
                  "preconditions": [],
                  "postconditions": ["Open Notepad"],
                  "timeout": null,
                  "depends_on": []
                },
                {
                  "sub_objective_id": "sub-2",
                  "objective": "Type the document header: 'Meeting Notes - [Date]'",
                  "domain": "desktop",
                  "target_server": "fake_desktop",
                  "preconditions": [],
                  "postconditions": ["Type the document header"],
                  "timeout": null,
                  "depends_on": []
                }
              ]
            }
            """
        )


def _registry() -> StrategyRegistry:
    server_script = Path(__file__).with_name("fake_strategy_server.py")
    registry = StrategyRegistry()
    for strategy_id, domain in (
        ("fake_web", "web"),
        ("fake_cli", "cli"),
        ("fake_desktop", "desktop"),
    ):
        registry.register(
            MCPStrategy(
                strategy_id=strategy_id,
                server_command=sys.executable,
                server_args=[str(server_script)],
                domain=domain,
                display_name=strategy_id,
                description=f"{domain} fake server",
                serial_execution=domain != "web",
            )
        )
    return registry


@pytest.mark.asyncio
async def test_objective_planner_routes_mixed_sub_objectives_by_capability():
    planner = ObjectivePlanner(strategy_registry=_registry(), llm_provider=None)

    plan = await planner.plan(
        TaskInput(
            task_id="mixed-1",
            description="Collect metrics, open dashboard, write note",
            domain="mixed",
            sub_objectives=[
                "Run systeminfo in the terminal",
                "Open http://example.com in the browser",
                "Open Notepad and write a summary",
            ],
        )
    )

    assert [step.target_server for step in plan.sub_objectives] == [
        "fake_cli",
        "fake_web",
        "fake_desktop",
    ]
    assert all(step.postconditions for step in plan.sub_objectives)


@pytest.mark.asyncio
async def test_objective_planner_preserves_all_approved_sub_objectives_when_llm_shrinks_plan():
    planner = ObjectivePlanner(strategy_registry=_registry(), llm_provider=_ShrinkingPlanLLM())
    approved = [
        "Open Notepad",
        "Type the document header: 'Meeting Notes - [Date]'",
        "Add three sections: Attendees, Agenda, Action Items with placeholder lines",
        "Save the file as meeting_notes_template.txt on the Desktop",
    ]

    plan = await planner.plan(
        TaskInput(
            task_id="desktop-template",
            description="Create a meeting notes template in Notepad",
            domain="desktop",
            sub_objectives=approved,
        )
    )

    assert [step.objective for step in plan.sub_objectives] == approved
    assert [step.sub_objective_id for step in plan.sub_objectives] == ["sub-1", "sub-2", "sub-3", "sub-4"]
    assert all(step.target_server == "fake_desktop" for step in plan.sub_objectives)


def test_objective_metadata_reports_missing_sub_objectives_against_plan():
    orchestrator = ObjectiveOrchestrator(
        config=TrinityConfig(gemini_api_key="test", openai_api_key="test"),
        llm_provider_factory=_FakeLLM,
    )
    plan = ObjectivePlan(
        objective_id="desktop-template",
        objective="Create a meeting notes template",
        sub_objectives=[
            SubObjective(
                sub_objective_id=f"sub-{index}",
                objective=f"step {index}",
                domain="desktop",
                target_server="fake_desktop",
            )
            for index in range(1, 5)
        ],
    )
    results = [
        SubObjectiveResult(
            sub_objective_id="sub-1",
            status="success",
            target_server="fake_desktop",
            domain="desktop",
        ),
        SubObjectiveResult(
            sub_objective_id="sub-2",
            status="success",
            target_server="fake_desktop",
            domain="desktop",
        ),
    ]

    metadata = orchestrator._objective_metadata(
        objective_plan=plan,
        sub_objective_results=results,
        evidence=ObjectiveEvidence(successful_sub_objectives=2),
        failed_sub_objective_id=None,
        failure_reason=None,
        duration_ms=10,
    )

    assert metadata["planned_sub_objectives"] == 4
    assert metadata["completed_sub_objectives"] == 2
    assert metadata["successful_sub_objectives"] == 2
    assert metadata["missing_sub_objective_ids"] == ["sub-3", "sub-4"]
    assert metadata["completion_confidence"] == 0.5


@pytest.mark.asyncio
async def test_objective_orchestrator_reports_localhost_prerequisite_missing(monkeypatch):
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, project_root: _registry()))
    orchestrator = ObjectiveOrchestrator(
        config=TrinityConfig(gemini_api_key="test", openai_api_key="test"),
        llm_provider_factory=_FakeLLM,
    )

    async with orchestrator:
        result = await orchestrator.execute(
            TaskInput(
                task_id="local-missing",
                description="Open local dashboard",
                domain="mixed",
                sub_objectives=["Open http://localhost:65530 in the browser"],
            )
        )

    assert result.status == "failure"
    assert result.category == "prerequisite_missing"
    assert "http://localhost:65530" in (result.error or "")
    assert result.metadata["failed_sub_objective_id"] == "sub-1"


@pytest.mark.asyncio
async def test_mid_chain_failure_aborts_remaining_sub_objectives(monkeypatch):
    """If sub-objective 2 fails, sub-objective 3 must never execute.

    Verifies: chain stops immediately on first failure; failed_sub_objective_id
    is set correctly; sub-3 appears in missing_sub_objective_ids.
    """
    monkeypatch.setattr(
        StrategyRegistry, "create_default", classmethod(lambda cls, project_root: _registry())
    )

    class _FailAt2LLM:
        async def call(self, messages, tools):
            sys_prompt = next(
                (m["content"] for m in messages if m.get("role") == "system"), ""
            )
            # Planning call — no system prompt; force fallback plan
            if not sys_prompt or not tools:
                return LLMResponse(text="null")

            has_prior = "PRIOR RESULTS" in sys_prompt
            has_tool_result = any(m.get("role") == "tool" for m in messages)

            if not has_prior:
                # Sub-1: succeed by calling a tool then returning final text
                if not has_tool_result:
                    return LLMResponse(
                        tool_calls=[ToolCall(id="t1", name="echo", arguments={"text": "sub-1-output"})]
                    )
                return LLMResponse(text="Sub-1 completed successfully")

            # Sub-2 (and sub-3 if erroneously reached): return text immediately
            # without any tool call — visible_tool_execution check fails → failure
            return LLMResponse(text="sub-2-no-tools")

    async with ObjectiveOrchestrator(
        config=TrinityConfig(gemini_api_key="test", openai_api_key="test"),
        llm_provider_factory=_FailAt2LLM,
    ) as orch:
        result = await orch.execute(
            TaskInput(
                task_id="chain-abort-1",
                description="Three CLI steps where step 2 fails",
                domain="cli",
                target_server="fake_cli",
                sub_objectives=[
                    "Run echo step-1 in the terminal",
                    "Run echo step-2 in the terminal",
                    "Run echo step-3 in the terminal",
                ],
            )
        )

    assert result.status == "failure", f"expected failure, got {result.status!r}"
    assert result.metadata["failed_sub_objective_id"] == "sub-2", (
        f"expected sub-2 to be the failed objective, got {result.metadata['failed_sub_objective_id']!r}"
    )
    assert result.metadata["successful_sub_objectives"] == 1, (
        f"only sub-1 should have succeeded, got {result.metadata['successful_sub_objectives']}"
    )
    assert "sub-3" in result.metadata["missing_sub_objective_ids"], (
        "sub-3 must appear in missing_sub_objective_ids — it must never have executed"
    )


def test_unified_app_mixed_domain_no_longer_defaults_to_browser():
    import sys
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[2] / "unified-app"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    from orchestrator.orchestrator_core import _resolve_domain

    assert _resolve_domain("mixed") == ("mixed", "")
