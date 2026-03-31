"""Real app-session desktop production workflow test."""
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


def test_desktop_production_workflow_uses_structured_desktop_result(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gemini_mock: object,
) -> None:
    """Run the desktop production smoke path through the real app submission flow."""
    if os.name != "nt":
        pytest.skip("desktop production E2E requires Windows")
    if os.getenv("TRINITY_RUN_LIVE", "0") != "1":
        pytest.skip("set TRINITY_RUN_LIVE=1 to run live desktop E2E coverage")

    objective = "Open Notepad and type PROD_DESKTOP_OK"
    queue_structured_plan(
        gemini_mock,
        step_description=objective,
        domain="desktop",
        expected_outcome="Notepad is opened and the desktop adapter reports successful actions.",
    )
    window = build_main_window(monkeypatch, tmp_path)

    try:
        run = submit_task_and_collect(
            app=app,
            window=window,
            description=objective,
            domain_label="Desktop",
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
    raw_result = step_payload["metadata"]["raw_result"]
    assert raw_result["status"] == "success"
    assert raw_result["successful_actions"] > 0
    assert step_payload["execution_log"], "Desktop workflow persisted no execution evidence"
    assert raw_result["metadata"].get("cleanup_warnings", []) == []
