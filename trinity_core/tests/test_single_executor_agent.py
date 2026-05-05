"""Unit tests for SingleExecutorAgent — test-protocol.md T1-T6."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trinity_core.models import TaskResult
from trinity_core.single_executor_agent import SingleExecutorAgent


def _make_strategy(strategy_id: str, domain: str) -> MagicMock:
    s = MagicMock()
    s.strategy_id = strategy_id
    s.domain = domain
    s.server_command = "python"
    s.server_args = []
    s.env = {}
    return s


def _make_registry(strategy_id: str = "cli_mcp", domain: str = "cli") -> MagicMock:
    registry = MagicMock()
    registry.get.return_value = _make_strategy(strategy_id, domain)
    registry.suggest_domain.side_effect = lambda task: (
        "desktop" if "notepad" in task.lower() else
        "cli" if "list" in task.lower() else
        "web"
    )
    registry.suggest_strategy_for_objective.return_value = strategy_id
    return registry


def _make_llm() -> MagicMock:
    return MagicMock()


def _make_executor_mock(status: str = "success", exec_log: list | None = None) -> MagicMock:
    ex = MagicMock()
    result = TaskResult(
        task_id="t1",
        status=status,
        category="success" if status == "success" else "sub_objective_failed",
        code=None,
        retriable=False,
        error=None,
        execution_log=exec_log or (
            [{"turn": 1, "action": "run_command", "result": "success", "details": "ok", "timestamp": "2026-01-01T00:00:00"}]
            if status == "success" else []
        ),
        artifacts=[],
        metadata={"output": "done"},
    )
    ex.execute = AsyncMock(return_value=result)
    ex.close = AsyncMock()
    ex.strategy = _make_strategy("cli_mcp", "cli")
    return ex


# T1: same strategy_id → same object (identity check)
def test_get_executor_same_strategy_returns_cached():
    agent = SingleExecutorAgent(_make_registry(), _make_llm())
    e1 = agent._get_executor("cli_mcp")
    e2 = agent._get_executor("cli_mcp")
    assert e1 is e2, "Expected same executor instance for same strategy_id"


# T2: different strategy_ids → different objects
def test_get_executor_different_strategies_return_different():
    registry = MagicMock()
    registry.get.side_effect = lambda sid: _make_strategy(sid, "cli")
    agent = SingleExecutorAgent(registry, _make_llm())
    e1 = agent._get_executor("cli_mcp")
    e2 = agent._get_executor("browser_mcp")
    assert e1 is not e2, "Expected different executor instances for different strategy_ids"


# T3: suggest_domain "open notepad" → "desktop"
def test_suggest_domain_notepad():
    agent = SingleExecutorAgent(_make_registry(), _make_llm())
    assert agent.suggest_domain("open notepad") == "desktop"


# T4: suggest_domain "list files" → "cli"
def test_suggest_domain_list_files():
    agent = SingleExecutorAgent(_make_registry(), _make_llm())
    assert agent.suggest_domain("list files") == "cli"


# T5: advisory verification — 1 success tool call, status="failure" → continues (no stop)
@pytest.mark.asyncio
async def test_advisory_verification_continues_if_tool_succeeded():
    registry = _make_registry()
    agent = SingleExecutorAgent(registry, _make_llm())

    failed_result_with_tool_work = TaskResult(
        task_id="t1",
        status="failure",
        category="sub_objective_failed",
        code="SUB_OBJ_FAIL",
        retriable=False,
        error="verification failed",
        execution_log=[
            {"turn": 1, "action": "run_command", "result": "success", "details": "cmd ran ok", "timestamp": "2026-01-01T00:00:00"}
        ],
        artifacts=[],
        metadata={"output": "did something"},
    )
    executor_mock = MagicMock()
    executor_mock.execute = AsyncMock(return_value=failed_result_with_tool_work)
    executor_mock.close = AsyncMock()
    executor_mock.strategy = _make_strategy("cli_mcp", "cli")

    with patch.object(agent, "_get_executor", return_value=executor_mock):
        result = await agent.run_objectives(
            task_id="run1",
            task_description="do stuff",
            objectives=["step one", "step two"],
            domain="cli",
        )

    assert result.status == "success", (
        "Expected success: both objectives had tool calls, advisory verification should not block"
    )


# T6: advisory with no tool calls + status=failure → returns failure immediately
@pytest.mark.asyncio
async def test_advisory_verification_fails_if_no_tool_calls():
    registry = _make_registry()
    agent = SingleExecutorAgent(registry, _make_llm())

    no_work_result = TaskResult(
        task_id="t1",
        status="failure",
        category="sub_objective_failed",
        code="SUB_OBJ_FAIL",
        retriable=False,
        error="nothing happened",
        execution_log=[],
        artifacts=[],
        metadata={"output": ""},
    )
    executor_mock = MagicMock()
    executor_mock.execute = AsyncMock(return_value=no_work_result)
    executor_mock.close = AsyncMock()
    executor_mock.strategy = _make_strategy("cli_mcp", "cli")

    with patch.object(agent, "_get_executor", return_value=executor_mock):
        result = await agent.run_objectives(
            task_id="run2",
            task_description="do stuff",
            objectives=["step one"],
            domain="cli",
        )

    assert result.status == "failure", (
        "Expected failure: no tool calls were made"
    )


# close() disconnects all cached executors
@pytest.mark.asyncio
async def test_close_disconnects_all_executors():
    registry = MagicMock()
    registry.get.side_effect = lambda sid: _make_strategy(sid, "cli")
    agent = SingleExecutorAgent(registry, _make_llm())

    mock_e1 = MagicMock()
    mock_e1.close = AsyncMock()
    mock_e2 = MagicMock()
    mock_e2.close = AsyncMock()

    agent._executors["cli_mcp"] = mock_e1
    agent._executors["browser_mcp"] = mock_e2

    await agent.close()

    mock_e1.close.assert_awaited_once()
    mock_e2.close.assert_awaited_once()
    assert agent._executors == {}, "Expected _executors to be cleared after close()"
