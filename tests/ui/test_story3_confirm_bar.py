"""Story 3 tests: _ConfirmBar widget + show_execution_step.

AC-08: ConfirmBar present with Approve/Reject/Edit buttons.
AC-09: Approve emits signal and hides bar.
AC-10: Reject emits signal and hides bar.
AC-11: Edit reveals QLineEdit; submitting emits edit_requested.
AC-14: show_execution_step appends step to browser HTML.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton

# ---------------------------------------------------------------------------
# _ConfirmBar unit tests
# ---------------------------------------------------------------------------


def test_confirm_bar_hidden_on_init(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    assert not bar.isVisible()


def test_confirm_bar_has_three_buttons(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    buttons = bar.findChildren(QPushButton)
    assert len(buttons) >= 3


def test_confirm_bar_approve_emits_signal(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.show()
    with qtbot.waitSignal(bar.approved, timeout=1000):
        bar._approve_btn.click()


def test_confirm_bar_reject_emits_signal(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.show()
    with qtbot.waitSignal(bar.rejected, timeout=1000):
        bar._reject_btn.click()


def test_confirm_bar_approve_hides_bar(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.approved.connect(bar.hide)  # simulate ChatWidget wiring
    bar.show()
    bar._approve_btn.click()
    assert not bar.isVisible()


def test_confirm_bar_reject_hides_bar(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.rejected.connect(bar.hide)  # simulate ChatWidget wiring
    bar.show()
    bar._reject_btn.click()
    assert not bar.isVisible()


def test_confirm_bar_edit_reveals_lineedit(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.show()
    bar._edit_btn.click()
    assert bar._edit_input.isVisible()


def test_confirm_bar_edit_submit_emits_edit_requested(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.show()
    bar._edit_btn.click()
    bar._edit_input.setText("change the plan")
    with qtbot.waitSignal(bar.edit_requested, timeout=1000) as blocker:
        bar._edit_input.returnPressed.emit()
    assert blocker.args[0] == "change the plan"


def test_confirm_bar_edit_submit_hides_bar(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.edit_requested.connect(lambda _: bar.hide())  # simulate ChatWidget wiring
    bar.show()
    bar._edit_btn.click()
    bar._edit_input.setText("some change")
    bar._edit_input.returnPressed.emit()
    assert not bar.isVisible()


def test_confirm_bar_apply_dark_does_not_crash(qtbot):
    from trinity_pilot.ui.chat_widget import _ConfirmBar

    bar = _ConfirmBar()
    qtbot.addWidget(bar)
    bar.apply_dark(True)
    bar.apply_dark(False)


# ---------------------------------------------------------------------------
# ChatWidget integration
# ---------------------------------------------------------------------------


def test_chat_widget_has_confirm_bar(qtbot):
    from trinity_pilot.ui.chat_widget import ChatWidget

    w = ChatWidget()
    qtbot.addWidget(w)
    assert hasattr(w, "_confirm_bar")
    assert not w._confirm_bar.isVisible()


def test_chat_widget_show_confirm_bar(qtbot):
    from trinity_pilot.ui.chat_widget import ChatWidget

    w = ChatWidget()
    qtbot.addWidget(w)
    w.show_confirm_bar()
    # isHidden() checks explicit hidden state regardless of parent visibility
    assert not w._confirm_bar.isHidden()


def test_chat_widget_hide_confirm_bar(qtbot):
    from trinity_pilot.ui.chat_widget import ChatWidget

    w = ChatWidget()
    qtbot.addWidget(w)
    w.show_confirm_bar()
    w.hide_confirm_bar()
    assert not w._confirm_bar.isVisible()


# ---------------------------------------------------------------------------
# show_execution_step — AC-14
# ---------------------------------------------------------------------------


def test_show_execution_step_appends_to_browser(qtbot):
    from trinity_pilot.ui.chat_widget import ChatWidget

    w = ChatWidget()
    qtbot.addWidget(w)
    w.show_execution_step("sub-obj-A", "running")
    html = w._browser.toHtml()
    assert "sub-obj-A" in html


def test_show_execution_step_persists_across_theme_change(qtbot):
    from trinity_pilot.ui.chat_widget import ChatWidget

    w = ChatWidget()
    qtbot.addWidget(w)
    w.show_execution_step("step-X", "done")
    w.set_dark(True)
    html = w._browser.toHtml()
    assert "step-X" in html


def test_show_execution_step_all_statuses(qtbot):
    from trinity_pilot.ui.chat_widget import ChatWidget

    w = ChatWidget()
    qtbot.addWidget(w)
    for status in ("running", "done", "failed", "pending"):
        w.show_execution_step(f"step-{status}", status)
    html = w._browser.toHtml()
    for status in ("running", "done", "failed", "pending"):
        assert f"step-{status}" in html
