"""Tests for desktop-targeted ObjectiveOrchestrator."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from trinity_core.action_store import ActionStore
from trinity_core.config import TrinityConfig
from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.mcp_client import MCPToolDescriptor
from trinity_core.models import TaskInput
from trinity_core.sub_objective_executor import SubObjectiveExecutor
import trinity_core.trinity as trinity_module
from trinity_core.strategy_registry import MCPStrategy, PromptContribution, StrategyRegistry
from trinity_core.trinity import ObjectiveOrchestrator


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_messages = []

    async def call(self, messages, tools):
        self.calls += 1
        self.seen_messages.append(messages)
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="inspect_state", arguments={})])
        return LLMResponse(text="done")


def _fake_strategy_registry(server_script: Path) -> StrategyRegistry:
    registry = StrategyRegistry()
    python_exe = sys.executable
    fake_strategy = MCPStrategy(
        strategy_id="fake_web",
        server_command=python_exe,
        server_args=[str(server_script)],
        domain="web",
        display_name="Fake Web Strategy",
        description="Fake strategy server for tests",
        prompt_contribution=PromptContribution(
            tool_guidance=["Use the visible fake tools directly."],
            forbidden_patterns=["Do not invent hidden tools."],
        ),
        serial_execution=False,
    )
    registry.register(fake_strategy)
    registry.register(
        MCPStrategy(
            strategy_id="fake_cli",
            server_command=python_exe,
            server_args=[str(server_script)],
            domain="cli",
            display_name="Fake CLI Strategy",
            description="Fake strategy server for tests",
            serial_execution=True,
        )
    )
    registry.register(
        MCPStrategy(
            strategy_id="fake_desktop",
            server_command=python_exe,
            server_args=[str(server_script)],
            domain="desktop",
            display_name="Fake Desktop Strategy",
            description="Fake strategy server for tests",
            serial_execution=True,
        )
    )
    return registry


@pytest.fixture
def executor_factory(monkeypatch):
    server_script = Path(__file__).with_name("fake_strategy_server.py")
    registry = _fake_strategy_registry(server_script)

    def _factory():
        monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, project_root: registry))
        config = TrinityConfig(
            gemini_api_key="test-gemini-key",
            openai_api_key="test-openai-key",
        )
        return ObjectiveOrchestrator(config=config, llm_provider_factory=_FakeLLM)

    return _factory


@pytest.mark.asyncio
async def test_trinity_executor_initialization(executor_factory):
    executor = executor_factory()
    await executor.initialize()
    assert executor.initialized
    await executor.shutdown()
    assert not executor.initialized


@pytest.mark.asyncio
async def test_trinity_executor_context_manager(executor_factory):
    async with executor_factory() as executor:
        assert executor.initialized


@pytest.mark.asyncio
async def test_trinity_executor_health_checks(executor_factory):
    async with executor_factory() as executor:
        health = await executor.health_check_all()
        assert health == {"fake_web": True, "fake_cli": True, "fake_desktop": True}


@pytest.mark.asyncio
async def test_trinity_executor_capabilities_show_visible_tools(executor_factory):
    async with executor_factory() as executor:
        caps = await executor.get_capabilities_all()
        assert caps["fake_web"]["strategy_id"] == "fake_web"
        assert "echo" in caps["fake_web"]["tools"]
        assert "inspect_state" in caps["fake_web"]["tools"]


@pytest.mark.asyncio
async def test_trinity_executor_returns_failure_when_strategy_unhealthy(executor_factory):
    async with executor_factory() as executor:
        class _UnhealthyRuntime:
            async def health_check(self) -> tuple[bool, None]:
                return False, None

            async def close(self) -> None:
                return None

        executor._build_sub_objective_executor = lambda strategy_id: _UnhealthyRuntime()
        result = await executor.execute(
            TaskInput(task_id="task-unhealthy", description="list files", domain="cli", target_server="fake_cli")
        )

    assert result.status == "failure"
    assert "not available" in (result.error or "")
    assert result.metadata.get("reason") == "health_check_failed"


@pytest.mark.asyncio
async def test_trinity_executor_executes_through_selected_strategy(executor_factory):
    async with executor_factory() as executor:
        result = await executor.execute(
            TaskInput(task_id="task-web", description="say hello", domain="web", target_server="fake_web")
        )

    assert result.status == "success"
    assert result.metadata["strategy_id"] == "fake_web"
    assert result.metadata["target_server"] == "fake_web"
    assert "inspect_state" in result.metadata["visible_tools"]
    system_prompt = executor._llm_provider.seen_messages[0][0]["content"]
    assert "Use the visible fake tools directly." in system_prompt
    assert "inspect_state" in system_prompt


@pytest.mark.asyncio
async def test_trinity_executor_builds_fresh_runtime_per_execution(executor_factory, monkeypatch):
    created = []
    original_build_sub_objective_executor = ObjectiveOrchestrator._build_sub_objective_executor

    def _tracked_build_sub_objective_executor(self, strategy_id):
        runtime = original_build_sub_objective_executor(self, strategy_id)
        created.append(runtime)
        return runtime

    monkeypatch.setattr(ObjectiveOrchestrator, "_build_sub_objective_executor", _tracked_build_sub_objective_executor)

    async with executor_factory() as executor:
        first = await executor.execute(
            TaskInput(task_id="task-web-1", description="say hello", domain="web", target_server="fake_web")
        )
        executor._llm_provider.calls = 0
        second = await executor.execute(
            TaskInput(task_id="task-web-2", description="say hello again", domain="web", target_server="fake_web")
        )

    assert first.status == "success"
    assert second.status == "success"
    execute_runtimes = [runtime for runtime in created if runtime.strategy.strategy_id == "fake_web"]
    assert len(execute_runtimes) >= 4  # health runtime + execution runtime for each objective
    assert execute_runtimes[1] is not execute_runtimes[3]


def test_sub_objective_executor_injects_action_memory_before_visible_tools(tmp_path):
    server_script = Path(__file__).with_name("fake_strategy_server.py")
    strategy = _fake_strategy_registry(server_script).get("fake_cli")
    store = ActionStore(db_path=tmp_path / "actions.db")
    for ts in (1.0, 2.0):
        store.write("cli", "list project files", "run_command", {"command": "Get-ChildItem"}, "success", ts=ts)
    for ts in range(3, 8):
        store.write(
            "cli",
            "list project files",
            "bad_command",
            {"command": "dir C:\\"},
            "failure",
            error_code="COMMAND_FAILED",
            ts=float(ts),
        )

    executor = SubObjectiveExecutor(strategy=strategy, llm_provider=_FakeLLM())
    executor._action_store = store
    executor._cached_descriptors = [
        MCPToolDescriptor(name="run_command", description="Run a shell command"),
        MCPToolDescriptor(name="bad_command", description="Run a bad shell command"),
    ]

    prompt = executor._build_system_prompt(
        TaskInput(task_id="task-memory", description="list project files", domain="cli")
    )

    assert "PROVEN PATTERNS" in prompt
    assert "run_command" in prompt
    assert "AVOID" in prompt
    assert "bad_command" in prompt
    assert "Last error: COMMAND_FAILED" in prompt
    assert prompt.index("PROVEN PATTERNS") < prompt.index("Visible tools:")


@pytest.mark.asyncio
async def test_trinity_executor_action_memory_write_failure_is_nonfatal(executor_factory, monkeypatch):
    class _BrokenStore:
        def format_prompt_section(self, domain, objective_text):
            return ""

        def write(self, *args, **kwargs):
            raise RuntimeError("store unavailable")

    broken_store = _BrokenStore()
    monkeypatch.setattr(SubObjectiveExecutor, "_get_action_store", lambda self: broken_store)

    async with executor_factory() as executor:
        result = await executor.execute(
            TaskInput(task_id="task-memory-nonfatal", description="say hello", domain="web", target_server="fake_web")
        )

    assert result.status == "success"


@pytest.mark.asyncio
async def test_trinity_executor_schedules_action_memory_write(executor_factory, monkeypatch):
    class _RecordingStore:
        def __init__(self):
            self.writes = []

        def format_prompt_section(self, domain, objective_text):
            return ""

        def write(self, *args, **kwargs):
            self.writes.append((args, kwargs))

    recording_store = _RecordingStore()
    monkeypatch.setattr(SubObjectiveExecutor, "_get_action_store", lambda self: recording_store)

    async with executor_factory() as executor:
        result = await executor.execute(
            TaskInput(task_id="task-memory-write", description="say hello", domain="web", target_server="fake_web")
        )
        await asyncio.sleep(0.1)

    assert result.status == "success"
    assert recording_store.writes
    args, kwargs = recording_store.writes[0]
    assert args[:5] == ("web", "say hello", "inspect_state", {}, "success")
    assert kwargs == {}
