"""Tests for status log panel."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from ui.panels.status_log_panel import StatusLogPanel
from ui.theme import APP_BG, SURFACE, TEXT


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_append_and_clear_log(app):
    panel = StatusLogPanel()
    assert APP_BG in panel.styleSheet()
    assert SURFACE in panel.log_text.styleSheet()
    assert TEXT in panel.log_text.styleSheet()
    panel.append_log("Task started", "info")
    panel.append_log("Task completed", "success")
    text = panel.log_text.toPlainText()
    assert "Task started" in text
    assert "Task completed" in text
    panel.clear_log()
    assert panel.log_text.toPlainText() == ""
