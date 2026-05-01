"""Tests for MCPStrategyClient timeout behaviour on call_tool and list_* methods."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from trinity_core.executor import TaskQueue
from trinity_core.mcp_client import MCPStrategyClient, MCPToolDescriptor
from trinity_core.models import TaskInput, TaskResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> MCPStrategyClient:
    client = MCPStrategyClient(command="echo", args=["ok"])
    client._connected = True
    client.session = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Unit tests — call_tool timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_raises_timeout_when_session_hangs():
    client = _make_client()

    async def _hang(*a, **kw):
        await asyncio.sleep(999)

    client.session.call_tool = _hang

    with pytest.raises(asyncio.TimeoutError):
        await client.call_tool("some_tool", {}, timeout=0.05)


@pytest.mark.asyncio
async def test_call_tool_succeeds_within_timeout():
    client = _make_client()
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text='{"status": "success", "output": "ok"}')]
    client.session.call_tool = AsyncMock(return_value=mock_result)

    result = await client.call_tool("some_tool", {}, timeout=5.0)
    assert result["status"] == "success"
    assert result["output"] == "ok"


# ---------------------------------------------------------------------------
# Unit tests — list_tools timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_raises_timeout_when_session_hangs():
    client = _make_client()

    async def _hang(*a, **kw):
        await asyncio.sleep(999)

    client.session.list_tools = _hang

    with pytest.raises(asyncio.TimeoutError):
        await client.list_tools(timeout=0.05)


@pytest.mark.asyncio
async def test_list_tools_succeeds_within_timeout():
    client = _make_client()
    tool1 = MagicMock(name="tool1", description="desc1", inputSchema={}, annotations=None)
    tool1.name = "tool1"
    tool2 = MagicMock(name="tool2", description="desc2", inputSchema={}, annotations=None)
    tool2.name = "tool2"
    mock_result = MagicMock()
    mock_result.tools = [tool1, tool2]
    client.session.list_tools = AsyncMock(return_value=mock_result)

    descriptors = await client.list_tools(timeout=5.0)
    assert len(descriptors) == 2
    assert descriptors[0].name == "tool1"
    assert descriptors[1].name == "tool2"


# ---------------------------------------------------------------------------
# Integration test — TaskQueue unblocks after call_tool timeout
# ---------------------------------------------------------------------------

class _HangingAdapter:
    """Adapter whose execute() hangs inside a simulated call_tool for `hang_seconds`."""

    def __init__(self, hang_seconds: float, task_id_out: list[str]) -> None:
        self._hang = hang_seconds
        self._task_id_out = task_id_out

    async def execute(self, task_input: TaskInput) -> TaskResult:
        client = _make_client()
        async def _hang(*a, **kw):
            await asyncio.sleep(999)

        client.session.call_tool = _hang
        try:
            await client.call_tool("hang_tool", {}, timeout=self._hang)
        except asyncio.TimeoutError:
            pass
        raise asyncio.TimeoutError("simulated call_tool timeout")

    async def close(self) -> None:
        pass


class _FastAdapter:
    """Adapter whose execute() returns success immediately."""

    def __init__(self, task_id_out: list[str]) -> None:
        self._out = task_id_out

    async def execute(self, task_input: TaskInput) -> TaskResult:
        self._out.append(task_input.task_id)
        return TaskResult(
            task_id=task_input.task_id,
            status="success",
            execution_log=[],
            artifacts=[],
            metadata={},
        )

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_task_queue_unblocks_after_call_tool_timeout():
    queue = TaskQueue(name="test-queue")
    await queue.start_worker()

    fast_completed: list[str] = []
    hanging_adapter = _HangingAdapter(hang_seconds=0.05, task_id_out=[])
    fast_adapter = _FastAdapter(task_id_out=fast_completed)

    task_hang = TaskInput(
        task_id="hang-task",
        description="this hangs",
        domain="desktop",
        context={},
        sub_objectives=[],
        verification_checks=[],
    )
    task_fast = TaskInput(
        task_id="fast-task",
        description="this is fast",
        domain="cli",
        context={},
        sub_objectives=[],
        verification_checks=[],
    )

    # Submit hanging task first, fast task second
    hang_result, fast_result = await asyncio.gather(
        queue.submit("hang-task", hanging_adapter, task_hang, timeout=2.0),
        queue.submit("fast-task", fast_adapter, task_fast, timeout=2.0),
    )

    await queue.stop_worker()

    # Hanging task must return failure, not hang indefinitely
    assert hang_result.status == "failure"
    assert hang_result.task_id == "hang-task"

    # Fast task must have executed — queue was not starved
    assert fast_result.status == "success"
    assert "fast-task" in fast_completed
