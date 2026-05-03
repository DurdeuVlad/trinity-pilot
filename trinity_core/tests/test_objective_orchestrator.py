from __future__ import annotations

import sys
from pathlib import Path

import pytest

from trinity_core.config import TrinityConfig
from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.models import TaskInput
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


def test_unified_app_mixed_domain_no_longer_defaults_to_browser():
    import sys
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[2] / "unified-app"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    from orchestrator.orchestrator_core import _resolve_domain

    assert _resolve_domain("mixed") == ("mixed", "")
