"""Unit tests: CLIAdapter forwards _prior_results to run_cli_automation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cli_io_models import CLITaskResult  # noqa: E402
from trinity_core.adapters.cli import CLIAdapter  # noqa: E402
from trinity_core.models import TaskInput  # noqa: E402


def _make_cli_result(status: str = "success") -> CLITaskResult:
    return CLITaskResult(
        status=status,
        total_actions=1,
        successful_actions=1,
        attempts=1,
        execution_log=[],
    )


@pytest.mark.asyncio
async def test_prior_results_forwarded_to_run_cli_automation() -> None:
    prior = {"obj1": {"desc": "browse page", "result": "some scraped text"}}
    mock_result = _make_cli_result("success")

    with patch(
        "trinity_core.adapters.cli.run_cli_automation",
        return_value=mock_result,
    ) as mock_run:
        task = TaskInput(
            task_id="c1",
            description="List Python files",
            domain="cli",
            context={"_prior_results": prior},
        )
        result = await CLIAdapter().execute(task)

    assert result.status == "success"
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("prior_results") == prior


@pytest.mark.asyncio
async def test_prior_results_is_none_when_absent() -> None:
    mock_result = _make_cli_result("success")

    with patch(
        "trinity_core.adapters.cli.run_cli_automation",
        return_value=mock_result,
    ) as mock_run:
        task = TaskInput(
            task_id="c2",
            description="echo hello",
            domain="cli",
            context={},
        )
        await CLIAdapter().execute(task)

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("prior_results") is None
