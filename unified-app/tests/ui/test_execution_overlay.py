"""Tests for the desktop takeover HUD overlay."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from ui.overlay import ExecutionOverlay


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_overlay_preserves_task_text_when_takeover_starts(app, qtbot) -> None:
    overlay = ExecutionOverlay()
    qtbot.addWidget(overlay)

    overlay.set_task("Open Chrome and search for the Phase 1 demo script.")
    overlay.show_for_domain("browser")
    qtbot.wait(10)

    assert "Open Chrome and search" in overlay._task_label.text()  # noqa: SLF001
    overlay.hide_overlay()
    qtbot.wait(10)


def test_overlay_tracks_plan_progress_and_marks_steps(app, qtbot) -> None:
    overlay = ExecutionOverlay()
    qtbot.addWidget(overlay)
    overlay.set_plan(["Step one", "Step two"])

    overlay.set_step_started(1, "Step one")
    overlay.set_step_completed(1)
    overlay.set_step_failed(2)

    assert overlay._progress_label.text() == "Step 1 of 2"  # noqa: SLF001
    assert overlay._progress_bar.value() == 1  # noqa: SLF001
    assert overlay._step_rows[0]._status == "completed"  # noqa: SLF001
    assert overlay._step_rows[1]._status == "failed"  # noqa: SLF001


def test_overlay_truncates_long_task_descriptions(app, qtbot) -> None:
    overlay = ExecutionOverlay()
    qtbot.addWidget(overlay)
    overlay.set_task("x" * 140)

    assert len(overlay._task_label.text()) <= 90  # noqa: SLF001
    assert overlay._task_label.text().endswith("...")  # noqa: SLF001
