"""Regression tests for native browser-agent text output mapping."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from browser_agent.core.io_models import AttemptLog, BrowserAgentOutput
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.models import TaskInput


@pytest.mark.asyncio
async def test_browser_adapter_exposes_native_extracted_text_as_text_output() -> None:
    task = TaskInput(
        task_id="native-read-1",
        description="Read the first paragraph from the page and return it.",
        domain="web",
        context={},
    )

    output = BrowserAgentOutput(
        session_id="s1",
        objective_id="o1",
        result="success",
        attempt_log=AttemptLog(
            actions=["extract_text first_meaningful_paragraph"],
            observations=["Cats are small, carnivorous mammals often kept as pets."],
            outcome="Extracted requested text.",
        ),
        extracted_text="Cats are small, carnivorous mammals often kept as pets.",
    )

    with patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
        return_value=output,
    ):
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["text_output"].startswith("Cats are small")
    assert result.execution_log[-1].details.startswith("Cats are small")

