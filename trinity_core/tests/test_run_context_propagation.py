"""Smoke tests: prior sub-objective outputs are injected into later objectives."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from trinity_core.config import TrinityConfig
from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.mcp_client import MCPToolDescriptor
from trinity_core.models import SubObjective, SubObjectiveResult, TaskInput
from trinity_core.strategy_registry import MCPStrategy, StrategyRegistry
from trinity_core.sub_objective_executor import SubObjectiveExecutor
from trinity_core.trinity import ObjectiveOrchestrator


_SERVER_SCRIPT = Path(__file__).with_name("fake_strategy_server.py")


def _registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    for strategy_id, domain in (
        ("fake_web", "web"),
        ("fake_cli", "cli"),
    ):
        registry.register(
            MCPStrategy(
                strategy_id=strategy_id,
                server_command=sys.executable,
                server_args=[str(_SERVER_SCRIPT)],
                domain=domain,
                display_name=strategy_id,
                description=f"{domain} fake server",
                serial_execution=False,
            )
        )
    return registry


class _RecordingLLM:
    """LLM stub that records every system prompt it receives.

    Tracks calls per-conversation by keying on the first user message text so
    that each sub-objective gets an independent odd/even parity (tool call on
    turn 1, text response on turn 2).
    """

    def __init__(self) -> None:
        self.system_prompts: list[str] = []
        self._per_task_calls: dict[str, int] = {}

    async def call(self, messages, tools):
        user_msg = next(
            (m["content"] for m in messages if m.get("role") == "user"), "default"
        )
        key = user_msg[:60]
        self._per_task_calls[key] = self._per_task_calls.get(key, 0) + 1
        turn = self._per_task_calls[key]

        sys_prompt = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )
        self.system_prompts.append(sys_prompt)

        if turn == 1:
            return LLMResponse(
                tool_calls=[ToolCall(id="1", name="echo", arguments={"text": f"result for: {key[:40]}"})]
            )
        return LLMResponse(text=f"done turn {turn}")


@pytest.mark.asyncio
async def test_second_objective_receives_first_output_in_system_prompt(monkeypatch):
    """The system prompt for objective 2 must contain the output of objective 1."""
    llm = _RecordingLLM()
    monkeypatch.setattr(
        StrategyRegistry, "create_default", classmethod(lambda cls, root: _registry())
    )

    async with ObjectiveOrchestrator(
        config=TrinityConfig(gemini_api_key="test", openai_api_key="test"),
        llm_provider_factory=lambda: llm,
    ) as orch:
        await orch.execute(
            TaskInput(
                task_id="ctx-test-1",
                description="Two CLI steps: gather then report",
                domain="cli",
                target_server="fake_cli",
                sub_objectives=[
                    "Run systeminfo in the terminal and capture CPU usage",
                    "Run echo with the captured CPU usage to confirm",
                ],
            )
        )

    assert len(llm.system_prompts) >= 2, "expected at least 2 LLM calls"

    first_prompt = llm.system_prompts[0]
    assert "PRIOR RESULTS" not in first_prompt, (
        "objective 1 must NOT have PRIOR RESULTS"
    )

    prompts_with_prior = [p for p in llm.system_prompts if "PRIOR RESULTS" in p]
    assert prompts_with_prior, "at least one later objective must have PRIOR RESULTS"
    second_prompt = prompts_with_prior[0]
    assert "cli" in second_prompt or "fake_cli" in second_prompt, (
        "PRIOR RESULTS must identify the source domain/server"
    )


@pytest.mark.asyncio
async def test_run_context_accumulates_across_three_objectives(monkeypatch):
    """By objective 3 the system prompt must list results from both obj 1 and obj 2."""
    llm = _RecordingLLM()
    monkeypatch.setattr(
        StrategyRegistry, "create_default", classmethod(lambda cls, root: _registry())
    )

    async with ObjectiveOrchestrator(
        config=TrinityConfig(gemini_api_key="test", openai_api_key="test"),
        llm_provider_factory=lambda: llm,
    ) as orch:
        await orch.execute(
            TaskInput(
                task_id="ctx-test-2",
                description="Three CLI steps in sequence",
                domain="cli",
                target_server="fake_cli",
                sub_objectives=[
                    "Run systeminfo in the terminal",
                    "Run ipconfig in the terminal",
                    "Run echo done in the terminal",
                ],
            )
        )

    prompts_with_prior = [p for p in llm.system_prompts if "PRIOR RESULTS" in p]
    assert prompts_with_prior, "objective 3 must have PRIOR RESULTS"
    third_prompt = prompts_with_prior[-1]
    prior_block = third_prompt[third_prompt.index("PRIOR RESULTS"):]
    assert prior_block.count("Output:") >= 2, (
        "objective 3 prompt must contain outputs from both objective 1 and 2"
    )


@pytest.mark.asyncio
async def test_first_objective_has_no_prior_results(monkeypatch):
    """Single-objective tasks must never inject a PRIOR RESULTS section."""
    llm = _RecordingLLM()
    monkeypatch.setattr(
        StrategyRegistry, "create_default", classmethod(lambda cls, root: _registry())
    )

    async with ObjectiveOrchestrator(
        config=TrinityConfig(gemini_api_key="test", openai_api_key="test"),
        llm_provider_factory=lambda: llm,
    ) as orch:
        await orch.execute(
            TaskInput(
                task_id="ctx-test-3",
                description="just one thing",
                domain="cli",
                target_server="fake_cli",
                sub_objectives=["Run python --version"],
            )
        )

    assert all(
        "PRIOR RESULTS" not in p for p in llm.system_prompts
    ), "single-objective task must not inject PRIOR RESULTS"


def test_build_system_prompt_renders_web_prior_result_in_cli_executor():
    """Unit: a cli executor's system prompt must contain a web objective's prior output."""
    strategy = MCPStrategy(
        strategy_id="fake_cli",
        server_command=sys.executable,
        server_args=[str(_SERVER_SCRIPT)],
        domain="cli",
        display_name="fake_cli",
        description="cli fake server",
        serial_execution=False,
    )
    executor = SubObjectiveExecutor(strategy=strategy, llm_provider=_RecordingLLM())
    executor._cached_descriptors = [
        MCPToolDescriptor(name="echo", description="Echo text"),
    ]

    web_prior = [
        {
            "sub_objective_id": "sub-1",
            "objective": "Navigate to python.org and extract the release version",
            "domain": "web",
            "output": "Python 3.12.3 is the latest stable release.",
        }
    ]

    task = TaskInput(
        task_id="cross-unit-1",
        description="Write the extracted version to a file",
        domain="cli",
        context={"prior_results": web_prior},
    )

    prompt = executor._build_system_prompt(task)

    assert "PRIOR RESULTS" in prompt, "PRIOR RESULTS section must be present"
    assert "Python 3.12.3" in prompt, "web output must appear verbatim in cli prompt"
    assert "sub-1" in prompt, "sub_objective_id must be referenced"
    assert "web" in prompt, "source domain must be identified"
    prior_idx = prompt.index("PRIOR RESULTS")
    tools_idx = prompt.index("Visible tools:")
    assert prior_idx < tools_idx, "PRIOR RESULTS must appear before the tools list"


@pytest.mark.asyncio
async def test_execute_sub_objective_injects_run_context_across_domains(monkeypatch):
    """Integration: run_context from a web step is present in sub_task.context for a cli step."""
    captured_contexts: list[dict] = []

    registry = _registry()
    monkeypatch.setattr(
        StrategyRegistry, "create_default", classmethod(lambda cls, root: registry)
    )

    web_run_context = [
        {
            "sub_objective_id": "sub-1",
            "objective": "Navigate to python.org and extract the release version",
            "domain": "web",
            "output": "Python 3.12.3 is the latest stable release.",
        }
    ]

    cli_sub_objective = SubObjective(
        sub_objective_id="sub-2",
        objective="Run echo Python 3.12.3 in the terminal",
        domain="cli",
        target_server="fake_cli",
    )

    original_execute = SubObjectiveExecutor.execute

    async def _capturing_execute(self, sub_task: TaskInput):
        captured_contexts.append(dict(sub_task.context or {}))
        return await original_execute(self, sub_task)

    monkeypatch.setattr(SubObjectiveExecutor, "execute", _capturing_execute)

    config = TrinityConfig(gemini_api_key="test", openai_api_key="test")

    async with ObjectiveOrchestrator(
        config=config,
        llm_provider_factory=_RecordingLLM,
    ) as orch:
        task = TaskInput(
            task_id="cross-unit-2",
            description="Write the Python version to the terminal",
            domain="cli",
            target_server="fake_cli",
        )
        await orch._execute_sub_objective(task, cli_sub_objective, run_context=web_run_context)

    assert captured_contexts, "execute must have been called"
    ctx = captured_contexts[0]
    assert "prior_results" in ctx, "prior_results must be injected into sub_task.context"
    assert ctx["prior_results"] == web_run_context
    assert ctx["prior_results"][0]["domain"] == "web", (
        "the web origin must be preserved in the injected context"
    )
    assert "Python 3.12.3" in ctx["prior_results"][0]["output"]
