"""CLIAdapter unit tests — run_cli_automation is mocked throughout.

No real CLI subprocess or Gemini planner required.  Tests verify:
  - Success / failure / exception status mapping
  - Category normalisation from CLITaskResult metadata
  - Cancelled-task early-exit contract
  - Execution-log pass-through to TaskResult
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cli_result(
    status: str = "success",
    error: str | None = None,
    reason: str | None = None,
    failure_category: str = "",
    actions: int = 1,
    successful: int = 1,
) -> Any:
    """Build a minimal CLITaskResult for use in mock return values."""
    from cli_io_models import CLIActionLog, CLITaskResult  # type: ignore[import]

    metadata: dict = {}
    if failure_category:
        metadata["failure_category"] = failure_category

    log = CLIActionLog(
        step=1,
        action="echo test",
        command="echo test",
        result="success" if status == "success" else "failure",
        exit_code=0 if status == "success" else 1,
    )
    return CLITaskResult(
        status=status,
        total_actions=actions,
        successful_actions=successful,
        attempts=1,
        execution_log=[log],
        error=error,
        reason=reason,
        metadata=metadata,
    )


def _make_task(task_id: str = "t1", cancel_event: Any = None) -> Any:
    from trinity_core.models import TaskInput  # type: ignore[import]

    return TaskInput(
        task_id=task_id,
        description="test cli task",
        domain="cli",
        cancel_event=cancel_event,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_adapter_success() -> None:
    """CLIAdapter maps backend status='success' to TaskResult(status='success')."""
    import trinity_core.adapters.cli  # noqa: F401 — ensures sys.path patched
    from trinity_core.adapters.cli import CLIAdapter

    mock_result = _make_cli_result(status="success")
    with patch(
        "trinity_core.adapters.cli.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await CLIAdapter().execute(_make_task("t1"))

    assert result.status == "success"
    assert result.task_id == "t1"
    assert result.error is None
    assert result.category == "success"


@pytest.mark.asyncio
async def test_cli_adapter_failure() -> None:
    """CLIAdapter maps backend status='failure' to TaskResult(status='failure')."""
    from trinity_core.adapters.cli import CLIAdapter

    mock_result = _make_cli_result(status="failure", error="command exited with code 1", successful=0)
    with patch(
        "trinity_core.adapters.cli.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await CLIAdapter().execute(_make_task("t2"))

    assert result.status == "failure"
    assert result.error == "command exited with code 1"
    assert result.category == "backend_error"


@pytest.mark.asyncio
async def test_cli_adapter_exception_returns_backend_error() -> None:
    """CLIAdapter wraps unexpected exceptions as TaskResult(status='failure', category='backend_error')."""
    from trinity_core.adapters.cli import CLIAdapter

    with patch(
        "trinity_core.adapters.cli.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=RuntimeError("subprocess crash"),
    ):
        result = await CLIAdapter().execute(_make_task("t3"))

    assert result.status == "failure"
    assert result.category == "backend_error"
    assert "subprocess crash" in (result.error or "")


@pytest.mark.asyncio
async def test_cli_adapter_cancelled_task_returns_failure_before_execution() -> None:
    """CLIAdapter returns failure immediately when cancel_event is already set."""
    from trinity_core.adapters.cli import CLIAdapter

    cancel = MagicMock()
    cancel.is_set.return_value = True

    with patch(
        "trinity_core.adapters.cli.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_thread:
        result = await CLIAdapter().execute(_make_task("t4", cancel_event=cancel))

    assert result.status == "failure"
    assert result.category == "cancelled"
    mock_thread.assert_not_called()  # backend never reached


@pytest.mark.asyncio
async def test_cli_adapter_normalizes_auth_failure_category() -> None:
    """_normalize_category maps auth-token failure to 'auth_failure'."""
    from trinity_core.adapters.cli import CLIAdapter

    mock_result = _make_cli_result(
        status="failure",
        failure_category="auth_failure",
        error="api_key_invalid",
        successful=0,
    )
    with patch(
        "trinity_core.adapters.cli.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await CLIAdapter().execute(_make_task("t5"))

    assert result.status == "failure"
    assert result.category == "auth_failure"


@pytest.mark.asyncio
async def test_cli_adapter_execution_log_populated() -> None:
    """CLIAdapter passes execution_log entries through to TaskResult."""
    from trinity_core.adapters.cli import CLIAdapter

    mock_result = _make_cli_result(status="success")
    with patch(
        "trinity_core.adapters.cli.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await CLIAdapter().execute(_make_task("t6"))

    assert len(result.execution_log) == 1
    log_entry = result.execution_log[0]
    assert log_entry.step == 1
    assert log_entry.action == "echo test"
