from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import orchestrator.orchestrator_core as core_module
from orchestrator.database import TaskStatus
from orchestrator.orchestrator_core import UnifiedAppObjectiveRunner

from .live_smoke_support import RecordingHistoryManager, patch_orchestrator_runtime


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


@pytest.fixture()
def live_runtime(monkeypatch: pytest.MonkeyPatch) -> RecordingHistoryManager:
    return patch_orchestrator_runtime(monkeypatch, core_module)


@pytest.mark.skipif(
    os.getenv("LIVE_GEMINI_SMOKE", "0") != "1" or os.getenv("RUN_BROWSER_INTEGRATION") != "1",
    reason="Set LIVE_GEMINI_SMOKE=1 and RUN_BROWSER_INTEGRATION=1 to run the live browser smoke test.",
)
async def test_live_browser_example_domain_reaches_completed(
    live_runtime: RecordingHistoryManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("GEMINI_API_KEY is required for live Gemini smoke")
    monkeypatch.setenv("TRINITY_AI_PROVIDER", "gemini")

    worker = UnifiedAppObjectiveRunner(
        "Open https://example.com and tell me the page title",
        "browser",
    )
    await worker._execute()

    assert live_runtime.completed_calls, "complete_task was never called"
    final = live_runtime.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    assert final["result_data"]

    completed_steps = [
        step for step in live_runtime.step_updates if step["status"] == TaskStatus.COMPLETED
    ]
    if completed_steps:
        assert all(step["result_data"] for step in completed_steps)
