from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import orchestrator.orchestrator_core as core_module
from orchestrator.database import TaskStatus
from orchestrator.orchestrator_core import OrchestratorWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from .live_smoke_support import RecordingHistoryManager, patch_orchestrator_runtime


@pytest.fixture()
def live_runtime(monkeypatch: pytest.MonkeyPatch) -> RecordingHistoryManager:
    return patch_orchestrator_runtime(monkeypatch, core_module)


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY", "").strip(),
    reason="GEMINI_API_KEY is required for live Gemini CLI smoke test.",
)
async def test_live_cli_directory_inspection_reaches_completed(
    live_runtime: RecordingHistoryManager,
) -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("GEMINI_API_KEY is required for live Gemini smoke")

    worker = OrchestratorWorker(
        "Show the current directory path and list its contents",
        "cli",
        provider_name="gemini",
        api_key=api_key,
    )
    await worker._execute()

    assert live_runtime.completed_calls, "complete_task was never called"
    final = live_runtime.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    assert final["result_data"] == {"status": "success", "category": "success"}

    completed_steps = [
        step for step in live_runtime.step_updates if step["status"] == TaskStatus.COMPLETED
    ]
    assert completed_steps, "No completed step payloads were recorded"
    assert all(step["result_data"]["status"] == "success" for step in completed_steps)
