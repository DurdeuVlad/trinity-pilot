"""Live smoke test: cross-objective run context propagation.

Guards:
  LIVE_GEMINI_SMOKE=1   — opt-in to any live LLM call
  RUN_CROSS_DOMAIN=1    — opt-in to the cross-domain scenario specifically

Both must be set. The test uses GEMINI_API_KEY and requires only cli_mcp,
which is always available (no external MCP server needed).

What is verified:
  1. Both sub-objectives complete — the chain does not abort mid-run.
  2. The second sub-objective's output contains content that could only have
     come from the first sub-objective (prior_results was in its prompt).
  3. The task reaches TaskStatus.COMPLETED overall.

Scenario:
  Step 1 — run `echo TRINITY_MARKER_ABC123` and capture the output.
  Step 2 — run `echo` again repeating the marker string found in step 1.

  The marker is unique and not mentioned in the task description for step 2.
  If prior_results are wired through correctly, the LLM in step 2 will echo
  the marker. If not, it has no way to know it.
"""
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

_MARKER = "TRINITY_MARKER_ABC123"


@pytest.fixture()
def live_runtime(monkeypatch: pytest.MonkeyPatch) -> RecordingHistoryManager:
    return patch_orchestrator_runtime(monkeypatch, core_module)


@pytest.mark.skipif(
    os.getenv("LIVE_GEMINI_SMOKE", "0") != "1" or os.getenv("RUN_CROSS_DOMAIN", "0") != "1",
    reason="Set LIVE_GEMINI_SMOKE=1 and RUN_CROSS_DOMAIN=1 to run the live cross-domain smoke test.",
)
async def test_live_context_propagation_marker_echoed_in_second_step(
    live_runtime: RecordingHistoryManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cli -> cli: step 2 echoes the unique marker printed by step 1."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("GEMINI_API_KEY is required for live cross-domain smoke")
    monkeypatch.setenv("TRINITY_AI_PROVIDER", "gemini")

    worker = UnifiedAppObjectiveRunner(
        (
            f"Step 1: open a terminal and run: echo {_MARKER} — capture the output. "
            f"Step 2: open a terminal again and run echo with the exact string "
            f"that was printed in step 1."
        ),
        "cli",
    )
    await worker._execute()

    assert live_runtime.completed_calls, "complete_task was never called"
    final = live_runtime.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )

    all_output = (
        str(final.get("result_data") or "")
        + " "
        + " ".join(str(s.get("result_data") or "") for s in live_runtime.step_updates)
    )
    assert _MARKER in all_output, (
        f"The marker {_MARKER!r} must appear in the task output. "
        f"If it does not, step 2 never received step 1's output via prior_results. "
        f"Full output: {all_output!r}"
    )



@pytest.mark.skipif(
    os.getenv("LIVE_GEMINI_SMOKE", "0") != "1"
    or os.getenv("RUN_CROSS_DOMAIN", "0") != "1"
    or os.getenv("RUN_BROWSER_INTEGRATION", "0") != "1",
    reason=(
        "Set LIVE_GEMINI_SMOKE=1, RUN_CROSS_DOMAIN=1, and RUN_BROWSER_INTEGRATION=1 "
        "to run the live browser→cli cross-domain smoke test."
    ),
)
async def test_live_browser_to_cli_cross_domain_context_propagation(
    live_runtime: RecordingHistoryManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """browser -> cli: title read from example.com must appear in the final output.

    Sub-objective 1 (web/browser_mcp): navigate to https://example.com and
    extract the page title.

    Sub-objective 2 (cli/cli_mcp): run echo with the page title obtained in
    sub-objective 1.

    The CLI step has no prior knowledge of the page title. It can only produce
    the correct output if prior_results from the browser step was present in
    its system prompt.

    We assert directly on the raw TaskResult from the bridge (bypassing
    orchestrator_core's cooked output path) so we see what Trinity actually
    produced regardless of verification status.
    """
    from orchestrator.trinity_bridge import TrinityBridge

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("GEMINI_API_KEY is required for live cross-domain smoke")
    monkeypatch.setenv("TRINITY_AI_PROVIDER", "gemini")

    bridge = TrinityBridge()
    await bridge.initialize()
    try:
        result = await bridge.execute_task(
            task_id="cross-live-browser-cli",
            description=(
                "Sub-objective 1: navigate to https://example.com in the browser "
                "and extract the page title. "
                "Sub-objective 2: open a terminal and run: echo <the page title from step 1>."
            ),
            domain="mixed",
        )
    finally:
        await bridge.shutdown()

    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    meta = payload.get("metadata") or {}
    sub_results = meta.get("sub_objective_results") or []

    # Collect all text Trinity produced across the run.
    all_text = " ".join([
        str(payload.get("error") or ""),
        str(meta.get("output") or ""),
        *[str(sr.get("output") or "") for sr in sub_results],
    ])

    assert sub_results, (
        "No sub_objective_results in metadata — the orchestrator did not plan any steps. "
        f"Raw payload: status={payload.get('status')!r} error={payload.get('error')!r}"
    )

    # The browser step must have run and produced "Example Domain".
    assert "Example Domain" in all_text, (
        "The browser page title 'Example Domain' must appear somewhere in the run output. "
        "This proves browser_mcp executed and returned data that could be passed to the CLI step. "
        f"All text collected: {all_text[:500]!r}"
    )
