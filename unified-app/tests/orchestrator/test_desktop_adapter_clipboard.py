"""Unit tests: DesktopAdapter forwards clipboard_content and _prior_results."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "unified-app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _make_desktop_result(status: str = "success"):
    from desktop_io_models import DesktopTaskResult  # type: ignore[import]

    return DesktopTaskResult(
        status=status,
        successful_actions=1,
        total_actions=1,
        execution_log=[],
    )


@pytest.mark.asyncio
async def test_clipboard_content_forwarded_to_run_desktop_automation() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result("success")
    mock_run = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_run):
        task = TaskInput(
            task_id="clip1",
            description="Paste text into Notepad",
            domain="desktop",
            context={"app_name": "Notepad", "clipboard_content": "hello world"},
        )
        result = await DesktopAdapter().execute(task)

    assert result.status == "success"
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("clipboard_content") == "hello world"


@pytest.mark.asyncio
async def test_prior_results_forwarded_to_run_desktop_automation() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result("success")
    prior = {"obj1": {"desc": "browse cats", "result": "Cats are fluffy."}}
    mock_run = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_run):
        task = TaskInput(
            task_id="prior1",
            description="Type summary in Notepad",
            domain="desktop",
            context={"app_name": "Notepad", "_prior_results": prior},
        )
        await DesktopAdapter().execute(task)

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("prior_results") == prior


@pytest.mark.asyncio
async def test_clipboard_and_prior_results_none_when_absent() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result("success")
    mock_run = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_run):
        task = TaskInput(
            task_id="absent1",
            description="Open Notepad",
            domain="desktop",
            context={"app_name": "Notepad"},
        )
        await DesktopAdapter().execute(task)

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("clipboard_content") is None
    assert call_kwargs.get("prior_results") is None


@pytest.mark.asyncio
async def test_world_state_forwarded_to_run_desktop_automation_async() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result("success")
    world_state = {"active_app": "Notepad", "app_launch_mode": "launched"}
    mock_run = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_run):
        task = TaskInput(
            task_id="ws1",
            description="Paste text into Notepad",
            domain="desktop",
            context={"app_name": "Notepad", "_world_state": world_state},
        )
        await DesktopAdapter().execute(task)

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("world_state") == world_state


@pytest.mark.asyncio
async def test_world_state_none_when_absent() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result("success")
    mock_run = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_run):
        task = TaskInput(
            task_id="ws2",
            description="Open Notepad",
            domain="desktop",
            context={"app_name": "Notepad"},
        )
        await DesktopAdapter().execute(task)

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs.get("world_state") is None
