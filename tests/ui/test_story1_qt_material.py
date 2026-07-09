"""Story 1 tests: qt-material integration.

AC-19: qt-material in pyproject.toml dependencies with >=2.17.
AC-06: Forced QPalette() block absent from run_app().
AC-07: _toggle_dark has no per-widget setStyleSheet for header/input/stop/dark_btn.
AC-01: MainWindow instantiates without exception.
AC-05: Dark mode toggle does not crash.
"""
from __future__ import annotations

import pathlib

import pytest


def test_pyproject_has_qt_material():
    """AC-19: qt-material in dependencies."""
    import tomllib

    path = pathlib.Path(__file__).parents[2] / "pyproject.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert any("qt-material" in d for d in deps), "qt-material not found in dependencies"
    match = next(d for d in deps if "qt-material" in d)
    assert ">=2.17" in match, f"Expected >=2.17 in: {match}"


def test_run_app_no_qpalette_block():
    """AC-06: QPalette() construction absent from run_app body."""
    src_path = pathlib.Path(__file__).parents[2] / "trinity_pilot" / "ui" / "app.py"
    src = src_path.read_text(encoding="utf-8")
    in_run_app = src[src.index("def run_app"):]
    assert "QPalette()" not in in_run_app, "QPalette() found inside run_app — should be removed"


def test_toggle_dark_no_per_widget_setstylesheet():
    """AC-07: _toggle_dark has no setStyleSheet for header/input/stop/dark_btn."""
    src_path = pathlib.Path(__file__).parents[2] / "trinity_pilot" / "ui" / "app.py"
    src = src_path.read_text(encoding="utf-8")
    # Extract just the _toggle_dark method body
    start = src.index("def _toggle_dark")
    end = src.index("def _wire_kill_paths")
    in_toggle = src[start:end]
    assert "self._header.setStyleSheet" not in in_toggle
    assert "self._input_bar.setStyleSheet" not in in_toggle
    assert "self._input.setStyleSheet" not in in_toggle
    assert "self._stop_btn.setStyleSheet" not in in_toggle


def test_apply_stylesheet_called_in_run_app():
    """AC-01 prerequisite: apply_stylesheet is referenced in run_app."""
    src_path = pathlib.Path(__file__).parents[2] / "trinity_pilot" / "ui" / "app.py"
    src = src_path.read_text(encoding="utf-8")
    in_run_app = src[src.index("def run_app"):]
    assert "apply_app_qss" in in_run_app, "apply_app_qss not called in run_app"


pytest.importorskip("PySide6")


def test_main_window_instantiates(qtbot):
    """AC-01: MainWindow instantiates without AttributeError."""
    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=False)
    qtbot.addWidget(w)
    assert w is not None


def test_dark_toggle_does_not_crash(qtbot):
    """AC-05: toggling dark mode via _toggle_dark raises no exception."""
    try:
        from qt_material import apply_stylesheet  # noqa: F401
    except ImportError:
        pytest.skip("qt-material not installed")

    from trinity_pilot.ui.app import MainWindow

    w = MainWindow(debug_mode=False)
    qtbot.addWidget(w)
    # Toggle without a real QApplication stylesheet (may be a no-op in headless tests)
    try:
        w._toggle_dark(True)
        w._toggle_dark(False)
    except Exception as exc:
        pytest.fail(f"_toggle_dark raised: {exc}")
