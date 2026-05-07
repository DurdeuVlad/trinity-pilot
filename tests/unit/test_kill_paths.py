"""Kill path tests — verifies all 3 kill paths are registered."""
import pytest

pytest.importorskip("PySide6", reason="PySide6 not installed")


class TestKillPaths:
    def test_pyautogui_failsafe_is_true(self):
        """Kill path 3: PyAutoGUI fail-safe must be True at module import."""
        import pyautogui
        import trinity_pilot.ui.app  # noqa: F401 — triggers FAILSAFE=True side effect
        assert pyautogui.FAILSAFE is True

    def test_stop_button_initially_disabled(self, qtbot):
        from trinity_pilot.ui.app import MainWindow
        window = MainWindow()
        qtbot.addWidget(window)
        assert not window._stop_btn.isEnabled()

    def test_stop_button_enables_when_running(self, qtbot):
        from trinity_pilot.ui.app import MainWindow
        window = MainWindow()
        qtbot.addWidget(window)
        window.set_running(True)
        assert window._stop_btn.isEnabled()
        assert not window._input.isEnabled()

    def test_stop_button_disables_after_stop(self, qtbot):
        from trinity_pilot.ui.app import MainWindow
        window = MainWindow()
        qtbot.addWidget(window)
        window.set_running(True)
        window.set_running(False)
        assert not window._stop_btn.isEnabled()
        assert window._input.isEnabled()

    def test_ctrl_shift_q_shortcut_registered(self, qtbot):
        """Kill path 2: Ctrl+Shift+Q shortcut must be registered on the window."""
        from PySide6.QtWidgets import QShortcut
        from trinity_pilot.ui.app import MainWindow
        window = MainWindow()
        qtbot.addWidget(window)

        shortcuts = window.findChildren(QShortcut)
        keys = [s.key().toString() for s in shortcuts]
        assert any("Ctrl+Shift+Q" in k for k in keys), f"Shortcuts found: {keys}"

    def test_log_message_includes_timestamp(self, qtbot):
        from trinity_pilot.ui.app import MainWindow
        window = MainWindow()
        qtbot.addWidget(window)
        window.log("test message")
        text = window._log_view.toPlainText()
        # Timestamp format [HH:MM:SS]
        import re
        assert re.search(r"\[\d{2}:\d{2}:\d{2}\]", text), f"No timestamp in: {text}"
