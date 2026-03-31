"""Tests for ChatPanel widget behavior."""
from __future__ import annotations

import inspect

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QTextEdit

from ui.panels.chat_panel import ChatPanel, ChatState
from ui.theme import APP_BG, ASSISTANT_ACCENT, BORDER, SURFACE


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_chat_panel_creates_without_error(app) -> None:
    panel = ChatPanel()
    assert panel is not None


def test_chat_panel_uses_dark_theme_surfaces(app) -> None:
    panel = ChatPanel()
    assert APP_BG in panel.styleSheet()
    assert SURFACE in panel.input_field.styleSheet()
    assert BORDER in panel.cancel_btn.styleSheet()
    assert ASSISTANT_ACCENT in panel.send_btn.styleSheet()


def test_composer_uses_multiline_text_edit(app) -> None:
    panel = ChatPanel()
    assert isinstance(panel.input_field, QTextEdit)


def test_initial_state_is_idle(app) -> None:
    panel = ChatPanel()
    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel.run_frame.isHidden()
    assert panel.input_field.isEnabled()
    assert panel.send_btn.isEnabled()


def test_add_message_user_increases_bubble_count(app) -> None:
    panel = ChatPanel()
    before = panel.messages_layout.count()
    panel.add_message("user", "hello")
    assert panel.messages_layout.count() == before + 1


def test_set_run_ready_reveals_run_frame_and_disables_composer(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("List all Python files.")

    assert panel._state is ChatState.READY_TO_RUN  # noqa: SLF001
    assert not panel.run_frame.isHidden()
    assert not panel.input_field.isEnabled()
    assert not panel.send_btn.isEnabled()
    assert panel.run_btn.isEnabled()
    assert panel.status_label.text() == "Ready to run. Click Run Workflow."


def test_run_button_emits_run_requested_with_confirmed_task(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("Echo hello.")

    spy = QSignalSpy(panel.run_requested)
    panel._on_run_clicked()

    assert len(spy) == 1
    assert list(spy[0]) == ["Echo hello."]


def test_set_input_enabled_false_moves_to_thinking(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    assert panel._state is ChatState.THINKING  # noqa: SLF001
    assert not panel.input_field.isEnabled()
    assert panel.status_label.text() == "Thinking..."


def test_set_input_enabled_true_returns_to_idle_after_assistant_reply(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_input_enabled(True)
    app.processEvents()

    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel.input_field.isEnabled()


def test_set_executing_true_enables_cancel_and_disables_run(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("Some task")
    panel.set_executing(True)

    assert panel._state is ChatState.EXECUTING  # noqa: SLF001
    assert not panel.input_field.isEnabled()
    assert not panel.run_btn.isEnabled()
    assert panel.cancel_btn.isEnabled()


def test_set_executing_true_allows_direct_submit_from_idle(app) -> None:
    panel = ChatPanel()

    panel.set_executing(True)

    assert panel._state is ChatState.EXECUTING  # noqa: SLF001
    assert not panel.run_frame.isHidden()
    assert panel.cancel_btn.isEnabled()


def test_set_executing_false_returns_to_idle(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("Some task")
    panel.set_executing(True)
    panel.set_executing(False)

    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel.input_field.isEnabled()
    assert not panel.cancel_btn.isEnabled()


def test_set_startup_state_block_hides_run_frame(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("Open app")
    panel.set_startup_state("API key missing.", block_submission=True)

    assert panel._state is ChatState.STARTUP_BLOCKED  # noqa: SLF001
    assert panel.run_frame.isHidden()
    assert not panel.input_field.isEnabled()
    assert panel.status_label.text() == "API key missing."


def test_set_startup_state_unblock_returns_to_idle(app) -> None:
    panel = ChatPanel()
    panel.set_startup_state("API key missing.", block_submission=True)
    panel.set_startup_state("Ready.", block_submission=False)

    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel.input_field.isEnabled()
    assert panel.status_label.text() == "Tell me what you'd like to automate."


def test_reset_for_new_session_stays_idle_after_healthy_startup(app) -> None:
    panel = ChatPanel()
    panel.set_startup_state("Ready.", block_submission=False)
    panel.add_message("assistant", "Ready to go.")
    panel.reset_for_new_session()

    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel.input_field.isEnabled()
    assert panel.status_label.text() == "Tell me what you'd like to automate."


def test_reset_for_new_session_clears_confirmed_task(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("Old task")
    panel.reset_for_new_session()

    assert panel._confirmed_task == ""  # noqa: SLF001
    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel.run_frame.isHidden()


def test_reset_for_new_session_preserves_startup_block(app) -> None:
    panel = ChatPanel()
    panel.set_startup_state("API key missing.", block_submission=True)
    panel.add_message("user", "msg1")
    panel.reset_for_new_session()

    assert panel._state is ChatState.STARTUP_BLOCKED  # noqa: SLF001
    assert not panel.input_field.isEnabled()
    assert panel.status_label.text() == "API key missing."


def test_startup_block_clears_stale_status_override(app) -> None:
    panel = ChatPanel()
    panel.load_task_draft("Rerun saved task", status_message="Loaded draft.")

    panel.set_startup_state("API key missing.", block_submission=True)

    assert panel._state is ChatState.STARTUP_BLOCKED  # noqa: SLF001
    assert panel.status_label.text() == "API key missing."


def test_send_empty_input_does_not_emit_message_sent(app) -> None:
    panel = ChatPanel()
    spy = QSignalSpy(panel.message_sent)
    panel.input_field.setPlainText("   ")
    panel._on_send()
    assert len(spy) == 0


def test_send_non_empty_input_emits_message_sent_and_enters_thinking(app) -> None:
    panel = ChatPanel()
    spy = QSignalSpy(panel.message_sent)
    panel.input_field.setPlainText("list files")
    panel._on_send()

    assert len(spy) == 1
    assert list(spy[0]) == ["list files"]
    assert panel._state is ChatState.THINKING  # noqa: SLF001
    assert panel.input_field.toPlainText() == ""


def test_send_too_long_input_keeps_state_and_clears_confirmed_task(app) -> None:
    panel = ChatPanel()
    panel._confirmed_task = "stale"  # noqa: SLF001
    panel.input_field.setPlainText("x" * 1001)

    panel._on_send()

    assert panel._state is ChatState.IDLE  # noqa: SLF001
    assert panel._confirmed_task == ""  # noqa: SLF001
    assert "cannot exceed" in panel.status_label.text()


def test_send_while_busy_state_does_not_emit(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    spy = QSignalSpy(panel.message_sent)
    panel.input_field.setPlainText("list files")
    panel._on_send()
    assert len(spy) == 0


def test_enter_key_sends_message(app) -> None:
    panel = ChatPanel()
    spy = QSignalSpy(panel.message_sent)
    panel.input_field.setPlainText("run something")
    panel.input_field.setFocus()

    QTest.keyClick(panel.input_field, Qt.Key.Key_Return)

    assert len(spy) == 1
    assert list(spy[0]) == ["run something"]


def test_shift_enter_inserts_newline(app) -> None:
    panel = ChatPanel()
    panel.input_field.setPlainText("line 1")
    panel.input_field.moveCursor(QTextCursor.MoveOperation.End)
    panel.input_field.setFocus()

    QTest.keyClick(panel.input_field, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(panel.input_field, "line 2")

    assert "line 1" in panel.input_field.toPlainText()
    assert "line 2" in panel.input_field.toPlainText()
    assert "\n" in panel.input_field.toPlainText()


def test_cancel_btn_emits_cancel_requested(app) -> None:
    panel = ChatPanel()
    panel.set_input_enabled(False)
    panel.set_run_ready("task")
    panel.set_executing(True)
    spy = QSignalSpy(panel.cancel_requested)
    panel.cancel_btn.click()
    assert len(spy) == 1


def test_reconcile_ui_is_only_interactive_state_mutator() -> None:
    source = inspect.getsource(ChatPanel)
    reconcile_source = inspect.getsource(ChatPanel._reconcile_ui)
    assert source.count(".setEnabled(") == reconcile_source.count(".setEnabled(")
    assert source.count(".setVisible(") == reconcile_source.count(".setVisible(")
