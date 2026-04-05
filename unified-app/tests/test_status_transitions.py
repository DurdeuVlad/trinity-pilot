"""Tests for failure, cancelled, and status panel state surfacing (UA-S5)."""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ui.panels.status_log_panel import _html_fail, _html_done, _html_cancelled, _RENDERERS


def test_status_panel_fail_renderer_present() -> None:
    assert "fail" in _RENDERERS


def test_status_panel_cancelled_renderer_present() -> None:
    assert "cancelled" in _RENDERERS


def test_status_panel_done_renderer_present() -> None:
    assert "done" in _RENDERERS


def test_status_fail_html_contains_failed_label() -> None:
    html = _html_fail("Unable to complete task", "12:00:00")
    assert "[failed]" in html
    assert "Unable to complete task" in html


def test_status_fail_html_reason_is_visible() -> None:
    reason = "target element not found"
    html = _html_fail(reason, "12:00:00")
    assert reason in html


def test_status_done_html_contains_done_label() -> None:
    html = _html_done("All steps completed successfully", "12:00:00")
    assert "[done]" in html


def test_status_cancelled_html_contains_cancelled_label() -> None:
    html = _html_cancelled("Stopped — cancelled by you.", "12:00:01")
    assert "[cancelled]" in html
    assert "Stopped" in html


def test_status_cancelled_html_distinct_from_fail() -> None:
    fail_html = _html_fail("task failed", "12:00:00")
    cancel_html = _html_cancelled("stopped", "12:00:00")
    # They must render different markup — different labels and colors
    assert "[failed]" not in cancel_html
    assert "[cancelled]" not in fail_html


def test_status_renderers_handle_html_escape() -> None:
    html = _html_fail("<script>alert('xss')</script>", "12:00:00")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_status_partial_uses_fail_level_by_default(qtbot) -> None:
    """Verify the runner final status uses 'fail' for partial outcomes."""
    from ui.panels.status_log_panel import StatusLogPanel
    panel = StatusLogPanel()
    qtbot.addWidget(panel)
    # Calling append_log with "fail" for a partial message should not raise
    panel.append_log("Partially done — completed 2 of 3 steps.", "fail")
    html_content = panel.log_text.toHtml()
    assert "[failed]" in html_content
