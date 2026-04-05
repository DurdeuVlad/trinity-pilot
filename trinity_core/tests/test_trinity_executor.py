"""Tests for TrinityExecutor."""
import pytest
import asyncio
from types import SimpleNamespace

from trinity_core.trinity import TrinityExecutor
from trinity_core.models import TaskInput

@pytest.mark.asyncio
async def test_trinity_executor_initialization():
    """Test executor initialization."""
    executor = TrinityExecutor()
    await executor.initialize()
    assert executor.initialized
    await executor.shutdown()
    assert not executor.initialized

@pytest.mark.asyncio
async def test_trinity_executor_context_manager():
    """Test context manager support."""
    async with TrinityExecutor() as executor:
        assert executor.initialized
    # Should auto-shutdown

@pytest.mark.asyncio
async def test_trinity_executor_health_checks():
    """Test health checks."""
    async with TrinityExecutor() as executor:
        health = await executor.health_check_all()
        assert isinstance(health, dict)
        assert "web" in health
        assert "desktop" in health
        assert "cli" in health

@pytest.mark.asyncio
async def test_trinity_executor_capabilities():
    """Test capability reporting."""
    async with TrinityExecutor() as executor:
        caps = await executor.get_capabilities_all()
        assert caps["web"]["constraints"]["thread_safe"] is True
        assert caps["desktop"]["constraints"]["thread_safe"] is False
        assert caps["cli"]["constraints"]["thread_safe"] is False


@pytest.mark.asyncio
async def test_trinity_executor_returns_failure_when_backend_unhealthy():
    """Unhealthy adapters should fail fast with a clean TaskResult payload."""
    async with TrinityExecutor() as executor:
        async def _unhealthy() -> bool:
            return False

        executor.adapters["cli"] = SimpleNamespace(
            health_check=_unhealthy,
            execute=None,
        )

        result = await executor.execute(
            TaskInput(task_id="task-unhealthy", description="list files", domain="cli")
        )

    assert result.status == "failure"
    assert "not available" in (result.error or "")
    assert result.metadata.get("reason") == "health_check_failed"
