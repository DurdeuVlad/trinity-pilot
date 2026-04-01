"""Tests for TrinityExecutor."""
import pytest
import asyncio
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
        assert caps["web"]["thread_safe"] is True
        assert caps["desktop"]["thread_safe"] is False
        assert caps["cli"]["thread_safe"] is False
