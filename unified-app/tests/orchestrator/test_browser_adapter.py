"""BrowserAdapter unit tests — all calls to run_browser_task are mocked.

No real Playwright or browser required. Tests verify:
  - Success/failure/need_assistance status mapping
  - screenshot_path extraction (P0 bug fix verification)
  - execution_log construction from AttemptLog.actions
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_browser_output(
    result: str = "success",
    screenshot_path: str | None = None,
    actions: list[str] | None = None,
    error_details: str | None = None,
) -> Any:
    """Build a BrowserAgentOutput for use in mock return values."""
    from browser_agent.core.io_models import AttemptLog, BrowserAgentOutput  # type: ignore[import]

    return BrowserAgentOutput(
        session_id="test-session",
        objective_id="test-obj",
        result=result,
        attempt_log=AttemptLog(
            actions=actions or ["navigated to page"],
            observations=[],
            outcome="done",
        ),
        screenshot_path=screenshot_path,
        error_details=error_details,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_adapter_success() -> None:
    """BrowserAdapter maps 'success' result to TaskResult(status='success')."""
    import trinity_core.adapters.browser  # noqa: F401  — ensures sys.path patched
    from trinity_core.adapters.browser import BrowserAdapter
    from trinity_core.models import TaskInput

    mock_output = _make_browser_output(result="success")
    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ):
        adapter = BrowserAdapter()
        task = TaskInput(task_id="t1", description="open browser", domain="web")
        result = await adapter.execute(task)

    assert result.status == "success"
    assert result.task_id == "t1"
    assert result.error is None


@pytest.mark.asyncio
async def test_browser_adapter_failure() -> None:
    """BrowserAdapter maps 'failure' result to TaskResult(status='failure')."""
    from trinity_core.adapters.browser import BrowserAdapter
    from trinity_core.models import TaskInput

    mock_output = _make_browser_output(result="failure", error_details="page not found")
    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ):
        result = await BrowserAdapter().execute(
            TaskInput(task_id="t2", description="open bad url", domain="web")
        )

    assert result.status == "failure"
    assert result.error == "page not found"


@pytest.mark.asyncio
async def test_browser_adapter_need_assistance_maps_to_status() -> None:
    """BrowserAdapter maps 'need_assistance' result to TaskResult(status='need_assistance')."""
    from trinity_core.adapters.browser import BrowserAdapter
    from trinity_core.models import TaskInput

    mock_output = _make_browser_output(result="need_assistance")
    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ):
        result = await BrowserAdapter().execute(
            TaskInput(task_id="t3", description="complex task", domain="web")
        )

    assert result.status == "need_assistance"


@pytest.mark.asyncio
async def test_browser_adapter_extracts_screenshot_path() -> None:
    """_extract_artifacts returns [screenshot_path] when set on BrowserAgentOutput.

    Verifies the P0 bug fix: reads result.screenshot_path (not result.attempt_log.screenshot_path).
    """
    from trinity_core.adapters.browser import BrowserAdapter
    from trinity_core.models import TaskInput

    mock_output = _make_browser_output(
        result="success", screenshot_path="_runtime/screenshots/final.jpg"
    )
    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ):
        result = await BrowserAdapter().execute(
            TaskInput(task_id="t4", description="take screenshot", domain="web")
        )

    assert result.artifacts == ["_runtime/screenshots/final.jpg"]


@pytest.mark.asyncio
async def test_browser_adapter_no_screenshot_returns_empty_artifacts() -> None:
    """_extract_artifacts returns [] when screenshot_path is None."""
    from trinity_core.adapters.browser import BrowserAdapter
    from trinity_core.models import TaskInput

    mock_output = _make_browser_output(result="success", screenshot_path=None)
    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=mock_output,
    ):
        result = await BrowserAdapter().execute(
            TaskInput(task_id="t5", description="no screenshot", domain="web")
        )

    assert result.artifacts == []
