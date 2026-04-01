"""Failure-category contract tests for Trinity adapters."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from browser_agent.core.io_models import AttemptLog, BrowserAgentOutput
from cli_io_models import CLITaskResult
from desktop_io_models import DesktopTaskResult
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.adapters.cli import CLIAdapter
from trinity_core.adapters.desktop import DesktopAdapter
from trinity_core.models import TaskInput


@pytest.mark.asyncio
async def test_browser_adapter_maps_need_assistance_to_user_error():
    adapter = BrowserAdapter()
    task = TaskInput(task_id="browser-help", description="find the right page", domain="web")

    with patch("trinity_core.adapters.browser.run_browser_task") as run_browser_task:
        run_browser_task.return_value = BrowserAgentOutput(
            session_id="browser-session",
            objective_id="browser-objective",
            result="need_assistance",
            error_details="Verification failed: expected outcome not visually confirmed.",
            attempt_log=AttemptLog(actions=["navigate"], observations=["page loaded"], outcome="needs help"),
        )

        result = await adapter.execute(task)

    assert result.status == "need_assistance"
    assert result.category == "user_error"


@pytest.mark.asyncio
async def test_cli_adapter_maps_auth_failure_category():
    adapter = CLIAdapter()
    task = TaskInput(task_id="cli-auth", description="list files", domain="cli")

    with patch("trinity_core.adapters.cli.run_cli_automation") as run_cli_automation:
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
    assert result.category == "auth_failure"


@pytest.mark.asyncio
async def test_cli_adapter_maps_timeout_failure_category():
    adapter = CLIAdapter()
    task = TaskInput(task_id="cli-timeout", description="run slow task", domain="cli")

    with patch("trinity_core.adapters.cli.run_cli_automation") as run_cli_automation:
        run_cli_automation.return_value = CLITaskResult(
            status="failure",
            total_actions=0,
            successful_actions=0,
            attempts=1,
            error="Command timed out after 60s",
            reason="timeout",
            metadata={"failure_category": "timeout"},
        )

        result = await adapter.execute(task)

    assert result.status == "failure"
    assert result.category == "timeout"


@pytest.mark.asyncio
async def test_desktop_adapter_maps_worker_start_failure_to_backend_error():
    adapter = DesktopAdapter()
    task = TaskInput(
        task_id="desktop-start-fail",
        description="open Notepad",
        domain="desktop",
        context={"app_name": "Notepad"},
    )

    with patch("trinity_core.adapters.desktop.run_desktop_automation") as run_desktop_automation:
        run_desktop_automation.return_value = DesktopTaskResult(
            status="failure",
            successful_actions=0,
            total_actions=0,
            error="Desktop worker returned no output",
            reason="desktop_worker_start_failed",
            metadata={"app_context": "Notepad"},
        )

        result = await adapter.execute(task)

    assert result.status == "failure"
    assert result.category == "backend_error"
