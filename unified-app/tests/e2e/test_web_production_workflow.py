"""Real app-session web production workflow test."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from ._e2e_support import build_main_window, queue_structured_plan, submit_task_and_collect


pytestmark = [pytest.mark.e2e, pytest.mark.live]


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_web_production_workflow_records_screenshot_artifact(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gemini_mock: object,
) -> None:
    """Run the web production smoke path through the real app submission flow."""
    if os.getenv("TRINITY_RUN_LIVE", "0") != "1":
        pytest.skip("set TRINITY_RUN_LIVE=1 to run live web E2E coverage")

    objective = "Open https://example.com and capture a screenshot"
    queue_structured_plan(
        gemini_mock,
        step_description=objective,
        domain="web",
        expected_outcome="A screenshot artifact is saved for the run.",
    )
    window = build_main_window(monkeypatch, tmp_path)

    try:
        run = submit_task_and_collect(
            app=app,
            window=window,
            description=objective,
            domain_label="Web",
            timeout_seconds=60.0,
        )
    finally:
        window.close()
        app.processEvents()

    assert run["status"] == "completed"
    assert not run["error_message"]
    assert run["step_payloads"], "No per-step result payload was persisted"

    step_payload = run["step_payloads"][-1]
    assert step_payload["status"] == "success"
    artifacts = step_payload["artifacts"]
    assert artifacts, "Browser workflow did not persist a screenshot artifact"

    screenshot_path = Path(artifacts[0])
    if not screenshot_path.is_absolute():
        screenshot_path = tmp_path / screenshot_path
    assert screenshot_path.exists()
    assert screenshot_path.stat().st_size > 0

    raw_result = step_payload["metadata"]["raw_result"]
    assert raw_result["result"] == "success"
