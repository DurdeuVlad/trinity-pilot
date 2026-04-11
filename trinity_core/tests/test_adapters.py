"""Tests for Trinity adapters."""
import pytest
import asyncio
from unittest.mock import patch

from trinity_core.models import TaskInput
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.adapters.desktop import DesktopAdapter
from trinity_core.adapters.cli import CLIAdapter

@pytest.mark.asyncio
async def test_browser_adapter_health():
    adapter = BrowserAdapter()
    assert await adapter.health_check()

@pytest.mark.asyncio
async def test_desktop_adapter_health():
    adapter = DesktopAdapter()
    assert await adapter.health_check()

@pytest.mark.asyncio
async def test_cli_adapter_health():
    adapter = CLIAdapter()
    assert await adapter.health_check()

@pytest.mark.asyncio
async def test_browser_adapter_capabilities():
    adapter = BrowserAdapter()
    caps = adapter.get_capabilities()
    assert caps["domain"] == "web"
    assert caps["constraints"]["async"] is True
    assert caps["constraints"]["thread_safe"] is True

@pytest.mark.asyncio
async def test_desktop_adapter_capabilities():
    adapter = DesktopAdapter()
    caps = adapter.get_capabilities()
    assert caps["domain"] == "desktop"
    assert caps["constraints"]["async"] is False
    assert caps["constraints"]["thread_safe"] is False

@pytest.mark.asyncio
async def test_cli_adapter_capabilities():
    adapter = CLIAdapter()
    caps = adapter.get_capabilities()
    assert caps["domain"] == "cli"
    assert caps["constraints"]["async"] is False


@pytest.mark.asyncio
async def test_cli_adapter_preserves_user_safe_failure_message():
    adapter = CLIAdapter()
    task = TaskInput(task_id="cli-fail", description="list files", domain="cli")

    with patch("trinity_core.adapters.cli.run_cli_automation") as run_cli_automation:
        from cli_io_models import CLITaskResult

        run_cli_automation.return_value = CLITaskResult(
            status="failure",
            total_actions=0,
            successful_actions=0,
            attempts=1,
            error="Gemini authentication failed. Check GEMINI_API_KEY before retrying.",
            reason="live_auth",
            metadata={"failure_category": "auth"},
        )

        result = await adapter.execute(task)

    assert result.status == "failure"
    assert "Gemini authentication failed" in (result.error or "")
    assert result.metadata["raw_result"]["metadata"]["failure_category"] == "auth"
