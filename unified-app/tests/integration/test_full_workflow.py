"""Light integration test for main-window signal wiring."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from main import MainWindow
from orchestrator import get_event_bus
from ui.theme import APP_BG, SURFACE

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_main_window_signal_wiring(app):
    window = MainWindow()
    bus = get_event_bus()

    assert not window.bottom_widget.isHidden()
    assert APP_BG in window.styleSheet()
    assert SURFACE in window.chat_panel.input_field.styleSheet()

    bus.emit_status("integration message", "info")
    text = window.status_log_panel.log_text.toPlainText()
    assert "integration message" in text

    bus.app_busy.emit(True)
    assert window.chat_panel.run_btn.isEnabled() is False
    window.close()


def test_main_window_close_uses_orchestrator_shutdown(app):
    window = MainWindow()

    class FakeOrchestrator:
        def __init__(self) -> None:
            self.shutdown_called = False

        def shutdown(self) -> None:
            self.shutdown_called = True

    fake_orchestrator = FakeOrchestrator()
    window.orchestrator = fake_orchestrator

    window.close()

    assert fake_orchestrator.shutdown_called is True


def test_main_window_history_selection_shows_details(app, tmp_path):
    window = MainWindow()
    window.history_view.set_history_manager(
        window.history_view.history_manager.__class__(str(tmp_path / "history.db"))
    )
    window.history_view.history_manager.create_task("history_1", "Open notepad", "desktop", ["Open app"])
    window.history_view.history_manager.add_step("history_1", 1, "Launch app")

    window.history_view.task_selected.emit("history_1")

    assert window.history_view.detail_summary.text() == "Open notepad"
    assert window.history_view.detail_task_id.text() == "history_1"
    assert window.history_view.steps_table.rowCount() == 1
    window.close()


def test_main_window_history_load_into_chat_populates_composer(app, tmp_path):
    window = MainWindow()
    window.history_view.set_history_manager(
        window.history_view.history_manager.__class__(str(tmp_path / "history.db"))
    )
    window.history_view.history_manager.create_task("history_2", "Open calculator", "desktop", ["Step one"])
    window.history_view.history_manager.add_step("history_2", 1, "Launch calculator")

    window.history_view.load_into_chat_requested.emit("history_2")

    assert window.tabs.currentIndex() == 0
    text = window.chat_panel.input_field.toPlainText()
    assert "Reuse this prior run as context:" in text
    assert "Open calculator" in text
    assert "desktop" in text
    window.close()


def test_main_window_history_rerun_emits_task_submission(app, tmp_path):
    window = MainWindow()
    window.history_view.set_history_manager(
        window.history_view.history_manager.__class__(str(tmp_path / "history.db"))
    )
    window.history_view.history_manager.create_task("history_3", "Open browser", "browser")

    captured: dict[str, str] = {}
    window.event_bus.task_submitted.disconnect()
    window.event_bus.task_submitted.connect(
        lambda description, domain: captured.update({"description": description, "domain": domain})
    )

    window.history_view.rerun_requested.emit("history_3")

    assert captured == {"description": "Open browser", "domain": "browser"}
    window.close()
