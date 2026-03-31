"""Tests for execution plan panel."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from ui.panels.execution_plan_panel import ExecutionPlanPanel
from ui.theme import APP_BG, BORDER, DANGER, SUCCESS, SURFACE, SURFACE_ALT, TEXT


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_display_plan_builds_steps(app):
    panel = ExecutionPlanPanel()
    panel.display_plan(["Step one", "Step two"])
    assert len(panel.step_widgets) == 2
    assert panel.step_widgets[0].status == "pending"
    assert APP_BG in panel.styleSheet()
    assert SURFACE_ALT in panel.empty_label.styleSheet()


def test_update_step_status(app):
    panel = ExecutionPlanPanel()
    panel.display_plan(["First", "Second"])
    panel.update_step_status(2, "running")
    assert panel.step_widgets[1].status == "running"


def test_step_styles_set_readable_foreground_colors(app):
    panel = ExecutionPlanPanel()
    panel.display_plan(["Readable step"])
    widget = panel.step_widgets[0]

    for status, expected in {
        "pending": TEXT,
        "running": TEXT,
        "completed": "#d7f7de",
        "failed": "#ffe0e0",
    }.items():
        widget.set_status(status)
        style = widget.styleSheet()
        assert f"color: {expected};" in style


def test_step_widgets_use_dark_surfaces(app):
    panel = ExecutionPlanPanel()
    panel.display_plan(["Readable step"])
    widget = panel.step_widgets[0]
    widget.set_status("pending")
    assert SURFACE in widget.styleSheet()
    widget.set_status("running")
    assert "#15283d" in widget.styleSheet()
    widget.set_status("completed")
    assert SUCCESS in widget.styleSheet()
    widget.set_status("failed")
    assert DANGER in widget.styleSheet()
    assert BORDER in panel.empty_label.styleSheet()
