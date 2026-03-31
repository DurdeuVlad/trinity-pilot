"""DesktopAdapter unit tests."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


def _make_desktop_result(
    status: str = "success",
    successful_actions: int = 1,
    total_actions: int = 1,
    error: str | None = None,
    reason: str | None = None,
) -> Any:
    """Build a DesktopTaskResult for use as mock return value."""
    from desktop_io_models import DesktopTaskResult  # type: ignore[import]

    return DesktopTaskResult(
        status=status,
        successful_actions=successful_actions,
        total_actions=total_actions,
        error=error,
        reason=reason,
        execution_log=[],
    )


@pytest.mark.asyncio
async def test_desktop_adapter_success() -> None:
    import trinity_core.adapters.desktop  # noqa: F401
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result(status="success")
    with patch(
        "trinity_core.adapters.desktop.run_desktop_automation_async",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await DesktopAdapter().execute(
            TaskInput(task_id="d1", description="Open Notepad", domain="desktop")
        )

    assert result.status == "success"
    assert result.task_id == "d1"


@pytest.mark.asyncio
async def test_desktop_adapter_failure() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result(
        status="failure",
        successful_actions=0,
        error="app not found",
        reason="window title did not match",
    )
    with patch(
        "trinity_core.adapters.desktop.run_desktop_automation_async",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await DesktopAdapter().execute(
            TaskInput(task_id="d2", description="Open Notepad", domain="desktop")
        )

    assert result.status == "failure"


@pytest.mark.asyncio
async def test_desktop_adapter_uses_app_name_from_context() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result()
    mock_fn = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_fn):
        await DesktopAdapter().execute(
            TaskInput(
                task_id="d3",
                description="Type in Notepad",
                domain="desktop",
                context={"app_name": "Notepad"},
            )
        )

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("target_app") == "Notepad"


@pytest.mark.asyncio
async def test_desktop_adapter_default_app_name_when_no_context() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result()
    mock_fn = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_fn):
        await DesktopAdapter().execute(
            TaskInput(task_id="d4", description="do something", domain="desktop")
        )

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("target_app") == "generic"


@pytest.mark.asyncio
async def test_desktop_adapter_execution_log_populated() -> None:
    from desktop_io_models import DesktopActionLog, DesktopTaskResult  # type: ignore[import]
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = DesktopTaskResult(
        status="success",
        successful_actions=1,
        total_actions=1,
        execution_log=[DesktopActionLog(step=1, action="click OK button", result="success")],
    )
    with patch(
        "trinity_core.adapters.desktop.run_desktop_automation_async",
        new=AsyncMock(return_value=mock_result),
    ):
        result = await DesktopAdapter().execute(
            TaskInput(task_id="d5", description="click button", domain="desktop")
        )

    assert len(result.execution_log) == 1
    assert result.execution_log[0].action == "click OK button"
    assert result.execution_log[0].result == "success"


@pytest.mark.asyncio
async def test_desktop_adapter_passes_runtime_timeout_and_app_exe_path() -> None:
    from trinity_core.adapters.desktop import DesktopAdapter
    from trinity_core.models import TaskInput

    mock_result = _make_desktop_result()
    mock_fn = AsyncMock(return_value=mock_result)
    with patch("trinity_core.adapters.desktop.run_desktop_automation_async", new=mock_fn):
        await DesktopAdapter().execute(
            TaskInput(
                task_id="d6",
                description="Open Notepad",
                domain="desktop",
                timeout=42,
                context={"app_name": "Notepad", "app_exe_path": "notepad.exe"},
            )
        )

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("runtime_timeout_seconds") == 42
    assert call_kwargs.get("app_exe_path") == "notepad.exe"


def test_desktop_runner_returns_timeout_failure_when_child_runtime_expires() -> None:
    from trinity_core.adapters.desktop import run_desktop_automation

    timeout_exc = subprocess.TimeoutExpired(cmd=["python", "generic_backend.py"], timeout=1)
    with patch("trinity_core.adapters.desktop.subprocess.run", side_effect=timeout_exc), patch(
        "trinity_core.adapters.desktop._resolve_backend_script",
        return_value="generic_backend.py",
    ):
        result = run_desktop_automation(
            objective="Open Notepad",
            target_app="Notepad",
            runtime_timeout_seconds=1,
        )

    assert result.status == "failure"
    assert result.reason == "desktop_task_timeout"
    assert "timed out after 1s" in (result.error or "")


def test_desktop_runner_parses_child_json_result() -> None:
    from trinity_core.adapters.desktop import run_desktop_automation

    child_stdout = json.dumps(
        {
            "status": "success",
            "successful_actions": 1,
            "total_actions": 1,
            "execution_log": [],
            "error": None,
            "reason": None,
            "context_history": [],
            "metadata": {"session_id": "desktop-session-test"},
        }
    )

    with patch(
        "trinity_core.adapters.desktop.subprocess.run",
        return_value=type("Completed", (), {"stdout": child_stdout, "stderr": "", "returncode": 0})(),
    ), patch(
        "trinity_core.adapters.desktop._resolve_backend_script",
        return_value="generic_backend.py",
    ):
        result = run_desktop_automation(
            objective="Open Notepad",
            target_app="Notepad",
            runtime_timeout_seconds=3,
        )

    assert result.status == "success"
    assert result.metadata["session_id"] == "desktop-session-test"


def test_desktop_runner_passes_absolute_pythonpath_to_child(monkeypatch: pytest.MonkeyPatch) -> None:
    from trinity_core.adapters.desktop import run_desktop_automation

    monkeypatch.setenv("PYTHONPATH", ".;unified-app")

    completed = type(
        "Completed",
        (),
        {
            "stdout": json.dumps(
                {
                    "status": "success",
                    "successful_actions": 1,
                    "total_actions": 1,
                    "execution_log": [],
                    "error": None,
                    "reason": None,
                    "context_history": [],
                    "metadata": {},
                }
            ),
            "stderr": "",
            "returncode": 0,
        },
    )()

    with patch(
        "trinity_core.adapters.desktop.subprocess.run",
        return_value=completed,
    ) as subprocess_run, patch(
        "trinity_core.adapters.desktop._resolve_backend_script",
        return_value="generic_backend.py",
    ):
        run_desktop_automation(
            objective="Open Notepad",
            target_app="Notepad",
            runtime_timeout_seconds=3,
        )

    child_env = subprocess_run.call_args.kwargs["env"]
    pythonpath_entries = child_env["PYTHONPATH"].split(os.pathsep)
    assert any(entry.endswith("desktop-ai-poc-modules") for entry in pythonpath_entries)
    assert any(entry.endswith("desktop-ai-poc-modules\\unified-app") for entry in pythonpath_entries)
    assert all(not entry.startswith(".") for entry in pythonpath_entries)
