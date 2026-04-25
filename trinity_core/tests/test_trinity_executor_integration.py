from __future__ import annotations

import sys
from pathlib import Path

import pytest

from trinity_core.config import TrinityConfig
from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.models import TaskInput
from trinity_core.strategy_registry import MCPStrategy, StrategyRegistry
from trinity_core.trinity import TrinityExecutor


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="inspect_state", arguments={})])
        return LLMResponse(text="done")


def _make_registry(server_script: Path) -> StrategyRegistry:
    registry = StrategyRegistry()
    python_exe = sys.executable
    registry.register(
        MCPStrategy(
            strategy_id="fake_web",
            server_command=python_exe,
            server_args=[str(server_script)],
            domain="web",
            display_name="Fake Web",
            description="Fake web strategy",
        )
    )
    registry.register(
        MCPStrategy(
            strategy_id="fake_web_alt",
            server_command=python_exe,
            server_args=[str(server_script)],
            domain="web",
            display_name="Fake Web Alt",
            description="Alternate fake web strategy",
        )
    )
    return registry

@pytest.mark.asyncio
async def test_executor_routes_browser_task_through_desktop_selected_target(monkeypatch):
    registry = _make_registry(Path(__file__).with_name("fake_strategy_server.py"))
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, project_root: registry))
    config = TrinityConfig(
        gemini_api_key="test-gemini-key",
        openai_api_key="test-openai-key",
    )

    async with TrinityExecutor(config=config, llm_provider_factory=_FakeLLM) as executor:
        result = await executor.execute(
            TaskInput(task_id="x2", description="navigate", domain="web", target_server="fake_web")
        )

    assert result.status == "success"
    assert result.metadata["strategy_id"] == "fake_web"
    assert result.metadata["target_server"] == "fake_web"


@pytest.mark.asyncio
async def test_executor_strategy_swap_changes_execution_path_without_code_changes(monkeypatch):
    registry = _make_registry(Path(__file__).with_name("fake_strategy_server.py"))
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, project_root: registry))
    config = TrinityConfig(
        gemini_api_key="test-gemini-key",
        openai_api_key="test-openai-key",
    )

    async with TrinityExecutor(config=config, llm_provider_factory=_FakeLLM) as executor:
        result = await executor.execute(
            TaskInput(task_id="x3", description="navigate", domain="web", target_server="fake_web_alt")
        )

    assert result.status == "success"
    assert result.metadata["strategy_id"] == "fake_web_alt"
    assert result.metadata["target_server"] == "fake_web_alt"
