"""Real app-session CLI production workflow test."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from ._e2e_support import build_main_window, queue_structured_plan, submit_task_and_collect


pytestmark = pytest.mark.e2e

CLI_OBJECTIVE = "create a file named cli_e2e_sentinel.txt that contains UNIFIED_APP_CLI_OK"
CLI_SENTINEL_PATH = Path("cli_e2e_sentinel.txt")
CLI_SENTINEL_TEXT = "UNIFIED_APP_CLI_OK"


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cli_production_workflow_uses_real_app_session(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gemini_mock: object,
) -> None:
    """Run the CLI production workflow through the real app submission flow."""
    queue_structured_plan(
        gemini_mock,
        step_description=CLI_OBJECTIVE,
        domain="cli",
        expected_outcome="cli_e2e_sentinel.txt exists and contains UNIFIED_APP_CLI_OK",
    )
    window = build_main_window(monkeypatch, tmp_path)

    try:
        run = submit_task_and_collect(
            app=app,
            window=window,
            description=CLI_OBJECTIVE,
            domain_label="CLI",
            timeout_seconds=30.0,
        )
    finally:
        window.close()

    assert run["status"] == "completed"
    assert not run["error_message"]
    assert run["step_payloads"], "No per-step result payload was persisted"

    step_payload = run["step_payloads"][-1]
    assert step_payload["status"] == "success"
