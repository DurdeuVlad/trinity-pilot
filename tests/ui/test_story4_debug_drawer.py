"""Story 4 tests: _DebugDrawer panel + Ctrl+Shift+D toggle.

AC-15: No debug drawer when debug_mode=False; no Ctrl+Shift+D shortcut.
AC-16: debug_mode=True shows drawer with ChatState text on toggle.
AC-17: Drawer shows pending_specs as structured text/JSON.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


# ---------------------------------------------------------------------------
# _DebugDrawer class tests
# ---------------------------------------------------------------------------


def test_debug_drawer_instantiates(qtbot):
    from trinity_pilot.ui.app import _DebugDrawer
    from trinity_pilot.ui.chat_widget import ChatState

    drawer = _DebugDrawer()
    qtbot.addWidget(drawer)
    assert drawer is not None


def test_debug_drawer_update_contains_chatstate(qtbot):
    from trinity_pilot.ui.app import _DebugDrawer
    from trinity_pilot.ui.chat_widget import ChatState

    drawer = _DebugDrawer()
    qtbot.addWidget(drawer)
    drawer.update(
        state=ChatState.AWAITING_CONFIRM,
        pending_specs=[{"objective_id": "obj_1", "domain": "cli"}],
        pending_request="test request",
        progress=None,
    )
    text = drawer._browser.toPlainText()
    assert "ChatState" in text


def test_debug_drawer_update_contains_pending_specs(qtbot):
    from trinity_pilot.ui.app import _DebugDrawer
    from trinity_pilot.ui.chat_widget import ChatState

    drawer = _DebugDrawer()
    qtbot.addWidget(drawer)
    drawer.update(
        state=ChatState.IDLE,
        pending_specs=[{"objective_id": "obj_spec_1", "domain": "cli"}],
        pending_request="",
        progress=None,
    )
    text = drawer._browser.toPlainText()
    assert "obj_spec_1" in text


def test_debug_drawer_update_contains_pending_request(qtbot):
    from trinity_pilot.ui.app import _DebugDrawer
    from trinity_pilot.ui.chat_widget import ChatState

    drawer = _DebugDrawer()
    qtbot.addWidget(drawer)
    drawer.update(
        state=ChatState.IDLE,
        pending_specs=[],
        pending_request="unique-request-string-xyz",
        progress=None,
    )
    text = drawer._browser.toPlainText()
    assert "unique-request-string-xyz" in text


def test_debug_drawer_has_fixed_height(qtbot):
    from trinity_pilot.ui.app import _DebugDrawer

    drawer = _DebugDrawer()
    qtbot.addWidget(drawer)
    assert drawer.maximumHeight() == 180


# ---------------------------------------------------------------------------
# MainWindow debug_mode=False gating — AC-15
# ---------------------------------------------------------------------------


def test_main_window_no_debug_drawer_when_debug_false(qtbot):
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=False)
    qtbot.addWidget(w)
    assert w._debug_drawer is None


def test_main_window_no_ctrl_shift_d_when_debug_false(qtbot):
    """Ctrl+Shift+D shortcut should not be registered in non-debug mode."""
    from PySide6.QtGui import QShortcut
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=False)
    qtbot.addWidget(w)
    shortcuts = w.findChildren(QShortcut)
    sequences = [s.key().toString() for s in shortcuts]
    assert "Ctrl+Shift+D" not in sequences


# ---------------------------------------------------------------------------
# MainWindow debug_mode=True — AC-16, AC-17
# ---------------------------------------------------------------------------


def test_main_window_has_debug_drawer_when_debug_true(qtbot):
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=True)
    qtbot.addWidget(w)
    assert w._debug_drawer is not None


def test_main_window_debug_drawer_hidden_initially(qtbot):
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=True)
    qtbot.addWidget(w)
    assert not w._debug_drawer.isVisible()


def test_main_window_toggle_debug_drawer_shows_it(qtbot):
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=True)
    qtbot.addWidget(w)
    w.show()
    w._toggle_debug_drawer()
    assert w._debug_drawer.isVisible()


def test_main_window_toggle_debug_drawer_twice_hides_it(qtbot):
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=True)
    qtbot.addWidget(w)
    w.show()
    w._toggle_debug_drawer()
    w._toggle_debug_drawer()
    assert not w._debug_drawer.isVisible()


def test_main_window_drawer_text_contains_chatstate_after_toggle(qtbot):
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=True)
    qtbot.addWidget(w)
    w._toggle_debug_drawer()
    text = w._debug_drawer._browser.toPlainText()
    assert "ChatState" in text


def test_ctrl_shift_d_registered_when_debug_true(qtbot):
    from PySide6.QtGui import QShortcut
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=True)
    qtbot.addWidget(w)
    shortcuts = w.findChildren(QShortcut)
    sequences = [s.key().toString() for s in shortcuts]
    assert "Ctrl+Shift+D" in sequences
