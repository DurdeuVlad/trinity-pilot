"""Unit tests: BrowserAdapter forwards _prior_results to run_browser_task."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from browser_agent.core.io_models import AttemptLog, BrowserAgentOutput  # noqa: E402
from trinity_core.adapters.browser import BrowserAdapter  # noqa: E402
from trinity_core.models import TaskInput  # noqa: E402


def _make_browser_output(result: str = "success") -> BrowserAgentOutput:
    return BrowserAgentOutput(
        session_id="s1",
        objective_id="o1",
        result=result,
        error_details=None,
        attempt_log=AttemptLog(
            attempt_number=1,
            actions=["navigate"],
            observations=["page loaded"],
            outcome="done",
        ),
    )


@pytest.mark.asyncio
async def test_prior_results_forwarded_to_run_browser_task() -> None:
    prior = {"obj1": {"desc": "do something", "result": "some text"}}
    mock_output = _make_browser_output("success")

    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ) as mock_run:
        task = TaskInput(
            task_id="b1",
            description="Open cats Wikipedia page",
            domain="web",
            context={"_prior_results": prior},
        )
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("prior_results") == prior


@pytest.mark.asyncio
async def test_prior_results_is_none_when_absent() -> None:
    mock_output = _make_browser_output("success")

    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ) as mock_run:
        task = TaskInput(
            task_id="b2",
            description="Go to example.com",
            domain="web",
            context={},
        )
        await BrowserAdapter().execute(task)

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("prior_results") is None
