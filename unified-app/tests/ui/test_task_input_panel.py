"""Tests for task input panel behavior."""
from __future__ import annotations

import pytest
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from ui.panels.task_input_panel import TaskInputPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_task_input_panel_creation(app):
    panel = TaskInputPanel()
    assert panel.task_input is not None
    assert panel.domain_combo.currentText() == "Auto-detect"


def test_domain_detection(app):
    panel = TaskInputPanel()
    assert panel.detect_domain("Search Google for weather") == "web"
    assert panel.detect_domain("Open Notepad and type text") == "desktop"
    assert panel.detect_domain("List files in this directory") == "cli"
    assert panel.detect_domain(
        "Open Wikipedia, copy the first paragraph from the page of cats and paste it in a new tab in Notepad"
    ) == "mixed"


def test_task_input_panel_applies_saved_default_domain(app):
    panel = TaskInputPanel()

    panel.set_default_domain("Desktop")

    assert panel.domain_combo.currentText() == "Desktop"


def test_task_input_panel_applies_saved_mixed_domain(app):
    panel = TaskInputPanel()

    panel.set_default_domain("Mixed")

    assert panel.domain_combo.currentText() == "Mixed"


def test_task_submission_signal(app):
    panel = TaskInputPanel()
    panel.task_input.setText("List files in current directory")
    spy = QSignalSpy(panel.task_submitted)
    panel.on_run_clicked()
    assert len(spy) == 1
    assert list(spy[0]) == ["List files in current directory", "cli"]


def test_empty_input_emits_validation_feedback(app):
    panel = TaskInputPanel()
    submit_spy = QSignalSpy(panel.task_submitted)
    validation_spy = QSignalSpy(panel.validation_error)

    panel.task_input.setText("   ")
    panel.on_run_clicked()

    assert len(submit_spy) == 0
    assert len(validation_spy) == 1
    assert "empty" in str(validation_spy[0][0]).lower()
    assert panel.run_btn.isEnabled() is True
    assert panel.cancel_btn.isEnabled() is False


def test_duplicate_submit_is_ignored_while_in_flight(app):
    panel = TaskInputPanel()
    panel.task_input.setText("List files in current directory")
    submit_spy = QSignalSpy(panel.task_submitted)
    duplicate_spy = QSignalSpy(panel.duplicate_submit_ignored)

    panel.on_run_clicked()
    panel.on_run_clicked()

    assert len(submit_spy) == 1
    assert len(duplicate_spy) == 1
    assert "ignored" in str(duplicate_spy[0][0]).lower()


def test_blocked_startup_mode_prevents_submission(app):
    panel = TaskInputPanel()
    panel.set_startup_state("Live Gemini blocked: missing API key.", block_submission=True)
    panel.task_input.setText("List files in current directory")
    submit_spy = QSignalSpy(panel.task_submitted)
    validation_spy = QSignalSpy(panel.validation_error)

    panel.on_run_clicked()

    assert len(submit_spy) == 0
    assert len(validation_spy) == 1
    assert "blocked" in str(validation_spy[0][0]).lower()
    assert panel.run_btn.isEnabled() is False


def test_oversized_input(app):
    panel = TaskInputPanel()
    submit_spy = QSignalSpy(panel.task_submitted)
    validation_spy = QSignalSpy(panel.validation_error)

    panel.task_input.setText("x" * 1001)
    panel.on_run_clicked()

    assert len(submit_spy) == 0
    assert len(validation_spy) == 1
    assert "1000" in str(validation_spy[0][0])


def test_valid_input(app):
    panel = TaskInputPanel()
    panel.task_input.setText("List files in current directory")
    spy = QSignalSpy(panel.task_submitted)

    panel.on_run_clicked()

    assert len(spy) == 1


def test_empty_input(app):
    panel = TaskInputPanel()
    submit_spy = QSignalSpy(panel.task_submitted)
    validation_spy = QSignalSpy(panel.validation_error)

    panel.task_input.setText("   ")
    panel.on_run_clicked()

    assert len(submit_spy) == 0
    assert len(validation_spy) == 1


def test_domain_selection(app):
    panel = TaskInputPanel()

    panel.set_default_domain("Desktop")

    assert panel.domain_combo.currentText() == "Desktop"


def test_duplicate_prevention(app):
    panel = TaskInputPanel()
    panel.task_input.setText("List files in current directory")
    submit_spy = QSignalSpy(panel.task_submitted)
    duplicate_spy = QSignalSpy(panel.duplicate_submit_ignored)

    panel.on_run_clicked()
    panel.on_run_clicked()

    assert len(submit_spy) == 1
    assert len(duplicate_spy) == 1
