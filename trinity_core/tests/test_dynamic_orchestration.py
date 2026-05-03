"""
Comprehensive integration tests for Dynamic MCP Orchestration.
Verifies that Trinity Core can mount any MCP server based on domain or target.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest
import asyncio

from trinity_core.config import TrinityConfig
from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.models import TaskInput
from trinity_core.strategy_registry import MCPStrategy, StrategyRegistry
from trinity_core.trinity import ObjectiveOrchestrator


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages = []

    async def call(self, messages, tools):
        self.calls += 1
        self.last_messages = messages
        if self.calls == 1:
            # Trigger a tool call to satisfy verification
            return LLMResponse(tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "hello"})])
        return LLMResponse(text="Task completed")


@pytest.fixture
def dynamic_registry():
    """Provides a registry that can be expanded during tests."""
    registry = StrategyRegistry()
    return registry


@pytest.fixture
def server_script():
    return Path(__file__).parent / "fake_strategy_server.py"


@pytest.fixture
def trinity_config():
    return TrinityConfig(
        gemini_api_key="test-key",
        openai_api_key="test-key",
        default_timeout=30
    )


@pytest.mark.asyncio
async def test_scenario_1_dynamic_domain_discovery(dynamic_registry, server_script, trinity_config, monkeypatch):
    """Confirm adding a new domain like 'excel' works without core changes."""
    python_exe = sys.executable
    
    # Register a completely new domain
    excel_strategy = MCPStrategy(
        strategy_id="excel_mcp",
        server_command=python_exe,
        server_args=[str(server_script)],
        domain="excel",
        display_name="Excel Strategy",
        description="Handles excel tasks",
    )
    dynamic_registry.register(excel_strategy)
    
    # Mock the registry creation to use our dynamic one
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, root: dynamic_registry))
    
    async with ObjectiveOrchestrator(config=trinity_config, llm_provider_factory=_FakeLLM) as executor:
        # Task with NO target_server, only domain="excel"
        task = TaskInput(
            task_id="t1",
            description="read excel file",
            domain="excel"
        )
        
        result = await executor.execute(task)
        
        if result.status != "success":
            print(f"DEBUG: result.error = {result.error}")
            print(f"DEBUG: result.metadata = {result.metadata}")
        
        assert result.status == "success"
        assert result.metadata["strategy_id"] == "excel_mcp"
        assert "echo" in result.metadata["visible_tools"]


@pytest.mark.asyncio
async def test_scenario_2_explicit_strategy_override(dynamic_registry, server_script, trinity_config, monkeypatch):
    """Confirm we can have multiple strategies for one domain and select one explicitly."""
    python_exe = sys.executable
    
    s1 = MCPStrategy(strategy_id="web_standard", server_command=python_exe, server_args=[str(server_script)], domain="web", display_name="S1", description="D1")
    s2 = MCPStrategy(strategy_id="web_playwright", server_command=python_exe, server_args=[str(server_script)], domain="web", display_name="S2", description="D2")
    
    dynamic_registry.register(s1)
    dynamic_registry.register(s2)
    
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, root: dynamic_registry))
    
    async with ObjectiveOrchestrator(config=trinity_config, llm_provider_factory=_FakeLLM) as executor:
        # Explicitly request the second one
        task = TaskInput(
            task_id="t2",
            description="browse",
            domain="web",
            target_server="web_playwright"
        )
        
        result = await executor.execute(task)
        assert result.metadata["strategy_id"] == "web_playwright"


@pytest.mark.asyncio
async def test_scenario_3_unified_capability_discovery(dynamic_registry, server_script, trinity_config, monkeypatch):
    """Confirm get_capabilities_all sees all registered strategies regardless of domain."""
    python_exe = sys.executable
    dynamic_registry.register(MCPStrategy(strategy_id="s1", server_command=python_exe, server_args=[str(server_script)], domain="d1", display_name="D1", description=""))
    dynamic_registry.register(MCPStrategy(strategy_id="s2", server_command=python_exe, server_args=[str(server_script)], domain="d2", display_name="D2", description=""))
    
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, root: dynamic_registry))
    
    async with ObjectiveOrchestrator(config=trinity_config, llm_provider_factory=_FakeLLM) as executor:
        caps = await executor.get_capabilities_all()
        
        assert "s1" in caps
        assert "s2" in caps
        assert "echo" in caps["s1"]["tools"]


@pytest.mark.asyncio
async def test_scenario_5_default_timeout_resolution(dynamic_registry, server_script, trinity_config, monkeypatch):
    """Verify unknown domains use the default_timeout."""
    python_exe = sys.executable
    dynamic_registry.register(MCPStrategy(strategy_id="custom", server_command=python_exe, server_args=[str(server_script)], domain="custom_domain", display_name="C", description="", serial_execution=True))
    
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, root: dynamic_registry))
    
    async with ObjectiveOrchestrator(config=trinity_config, llm_provider_factory=_FakeLLM) as executor:
        task = TaskInput(task_id="t5", description="test", domain="custom_domain")
        
        # We check the internal resolution of timeout
        timeout = executor._timeout_for_domain(task)
        assert timeout == 30 # from trinity_config.default_timeout


@pytest.mark.asyncio
async def test_scenario_6_fault_isolation_for_new_domains(dynamic_registry, trinity_config, monkeypatch):
    """Verify broken strategies return structured errors."""
    # Register a strategy with a non-existent command
    broken_strategy = MCPStrategy(
        strategy_id="broken",
        server_command="non_existent_command_12345",
        server_args=[],
        domain="broken_domain",
        display_name="Broken",
        description="",
    )
    dynamic_registry.register(broken_strategy)
    
    monkeypatch.setattr(StrategyRegistry, "create_default", classmethod(lambda cls, root: dynamic_registry))
    
    async with ObjectiveOrchestrator(config=trinity_config, llm_provider_factory=_FakeLLM) as executor:
        task = TaskInput(task_id="t6", description="test", domain="broken_domain")
        
        result = await executor.execute(task)
        
        assert result.status == "failure"
        assert result.category == "health_check_failed"
        assert "broken" in result.metadata["strategy_id"]
