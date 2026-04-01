"""Contract tests for Trinity adapter timeout and cancellation behavior."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

import pytest

from cli_io_models import CLITaskResult
from desktop_io_models import DesktopTaskResult
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.adapters.cli import CLIAdapter
from trinity_core.adapters.desktop import DesktopAdapter
from trinity_core.models import TaskInput


@pytest.mark.asyncio
async def test_browser_adapter_enforces_effective_timeout():
    adapter = BrowserAdapter()
    task = TaskInput(
        task_id="browser-timeout",
        description="open example.com",
        domain="web",
        timeout=1,
    )

    async def slow_browser_task(**_kwargs):
        await asyncio.sleep(1.5)
        raise AssertionError("browser timeout wrapper did not stop the slow task")

    with patch("trinity_core.adapters.browser.run_browser_task", side_effect=slow_browser_task):
        result = await adapter.execute(task)

    assert result.status == "failure"
    assert result.category == "timeout"
    assert result.metadata["effective_timeout_seconds"] == 1


@pytest.mark.asyncio
async def test_cli_adapter_passes_effective_timeout_to_backend():
    adapter = CLIAdapter()
    task = TaskInput(
        task_id="cli-timeout-forwarding",
        description="dir",
        domain="cli",
        timeout=42,
    )

    with patch("trinity_core.adapters.cli.run_cli_automation") as run_cli_automation:
        run_cli_automation.return_value = CLITaskResult(
            status="success",
            total_actions=1,
            successful_actions=1,
            attempts=1,
            metadata={},
        )

        result = await adapter.execute(task)

    assert result.status == "success"
    assert run_cli_automation.call_args.kwargs["timeout"] == 42
    assert result.metadata["effective_timeout_seconds"] == 42


@pytest.mark.asyncio
async def test_desktop_adapter_short_circuits_when_cancelled_before_start():
    adapter = DesktopAdapter()
    cancel_event = threading.Event()
    cancel_event.set()
    task = TaskInput(
        task_id="desktop-cancelled",
        description="open Notepad",
        domain="desktop",
        context={"app_name": "Notepad"},
        cancel_event=cancel_event,
    )

    with patch("trinity_core.adapters.desktop.run_desktop_automation") as run_desktop_automation:
        result = await adapter.execute(task)

    run_desktop_automation.assert_not_called()
    assert result.status == "failure"
    assert result.category == "cancelled"


@pytest.mark.asyncio
async def test_desktop_adapter_emits_semantic_output_for_open_actions():
    adapter = DesktopAdapter()
    task = TaskInput(
        task_id="desktop-open-output",
        description="Open Notepad",
        domain="desktop",
        context={"app_name": "Notepad", "app_exe_path": "notepad.exe"},
    )

    with patch("trinity_core.adapters.desktop.run_desktop_automation_async") as run_desktop_automation_async:
        run_desktop_automation_async.return_value = DesktopTaskResult(
            status="success",
            successful_actions=1,
            total_actions=1,
            execution_log=[],
            metadata={"app_context": "Notepad"},
        )

        result = await adapter.execute(task)

    assert result.status == "success"
    assert result.metadata["output"] == "Open Notepad"


@pytest.mark.asyncio
async def test_desktop_adapter_normalizes_blank_document_open_output():
    adapter = DesktopAdapter()
    task = TaskInput(
        task_id="desktop-open-blank-doc-output",
        description="Open Notepad and create a new blank document",
        domain="desktop",
        context={"app_name": "Notepad", "app_exe_path": "notepad.exe"},
    )

    with patch("trinity_core.adapters.desktop.run_desktop_automation_async") as run_desktop_automation_async:
        run_desktop_automation_async.return_value = DesktopTaskResult(
            status="success",
            successful_actions=1,
            total_actions=1,
            execution_log=[],
            metadata={"app_context": "Notepad"},
        )

        result = await adapter.execute(task)

    assert result.status == "success"
    assert result.metadata["output"] == "Open Notepad"
