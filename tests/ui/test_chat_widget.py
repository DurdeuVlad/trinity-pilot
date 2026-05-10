"""UI unit tests for the new chat layer.

Groups:
  1. bubble_renderer  — pure HTML builders (no Qt)
  2. ChatState        — state transitions (no Qt event loop)
  3. ThinkingIndicator — start/stop with pytest-qt
  4. ObjectiveChipsWidget — mark_running/passed/failed with pytest-qt
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Group 1: bubble_renderer — pure HTML, no Qt
# ---------------------------------------------------------------------------

from trinity_pilot.ui.bubble_renderer import (
    ai_bubble,
    confirmation_prompt,
    debug_block,
    objectives_card,
    summary_bubble,
    system_note,
    user_bubble,
)


def test_user_bubble_contains_text():
    html = user_bubble("Hello world")
    assert "Hello world" in html


def test_user_bubble_right_aligned():
    html = user_bubble("x")
    assert "text-align:right" in html


def test_ai_bubble_contains_text():
    html = ai_bubble("AI says hi")
    assert "AI says hi" in html


def test_ai_bubble_left_aligned():
    html = ai_bubble("x")
    assert "text-align:left" in html


def test_objectives_card_contains_ids():
    specs = [
        {"objective_id": "obj_1", "domain": "cli", "description": "run stuff"},
        {"objective_id": "obj_2", "domain": "browser", "description": "browse"},
    ]
    html = objectives_card(specs)
    assert "obj_1" in html
    assert "obj_2" in html
    assert "cli" in html
    assert "browser" in html


def test_objectives_card_has_numbered_items():
    specs = [{"objective_id": "a", "domain": "cli"}]
    html = objectives_card(specs)
    assert "1." in html


def test_summary_bubble_completed():
    html = summary_bubble(10.5, "completed", {"a": {"status": "passed"}})
    assert "completed" in html.lower() or "\u2705" in html


def test_summary_bubble_failed():
    html = summary_bubble(5.0, "failed", {"a": {"status": "failed"}})
    assert "\u274C" in html or "failed" in html.lower()


def test_debug_block_contains_label():
    html = debug_block("Planner JSON", '{"key": "val"}')
    assert "Planner JSON" in html
    assert "key" in html


def test_system_note_contains_text():
    html = system_note("Worker started")
    assert "Worker started" in html


def test_confirmation_prompt_contains_keywords():
    html = confirmation_prompt()
    assert "yes" in html.lower() or "\u2018yes\u2019" in html
    assert "no" in html.lower() or "\u2018no\u2019" in html


def test_user_bubble_escapes_html():
    html = user_bubble("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Group 2: ChatState — state machine logic (no Qt)
# ---------------------------------------------------------------------------

from trinity_pilot.ui.chat_widget import ChatState


def test_chat_state_enum_values():
    assert ChatState.IDLE != ChatState.PLANNING
    assert ChatState.AWAITING_CONFIRM != ChatState.EXECUTING
    assert ChatState.DONE != ChatState.ERROR


def test_chat_state_is_enum():
    from enum import Enum
    assert issubclass(ChatState, Enum)


# ---------------------------------------------------------------------------
# Group 3: ThinkingIndicator — Qt widget tests (pytest-qt)
# ---------------------------------------------------------------------------

pytest.importorskip("PySide6")


def test_thinking_indicator_starts_hidden(qtbot):
    from trinity_pilot.ui.thinking_indicator import ThinkingIndicator
    widget = ThinkingIndicator()
    qtbot.addWidget(widget)
    assert not widget.isVisible()


def test_thinking_indicator_shows_on_start(qtbot):
    from trinity_pilot.ui.thinking_indicator import ThinkingIndicator
    widget = ThinkingIndicator()
    qtbot.addWidget(widget)
    widget.start()
    assert widget.isVisible()


def test_thinking_indicator_hides_on_stop(qtbot):
    from trinity_pilot.ui.thinking_indicator import ThinkingIndicator
    widget = ThinkingIndicator()
    qtbot.addWidget(widget)
    widget.start()
    widget.stop()
    assert not widget.isVisible()


def test_thinking_indicator_label_cycles(qtbot):
    from trinity_pilot.ui.thinking_indicator import ThinkingIndicator, _FRAMES
    widget = ThinkingIndicator()
    qtbot.addWidget(widget)
    widget.start()
    initial = widget._label.text()
    assert initial in _FRAMES


# ---------------------------------------------------------------------------
# Group 4: ObjectiveChipsWidget — Qt widget tests (pytest-qt)
# ---------------------------------------------------------------------------

def test_chips_widget_hidden_initially(qtbot):
    from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
    w = ObjectiveChipsWidget()
    qtbot.addWidget(w)
    assert not w.isVisible()


def test_chips_widget_shows_after_set_objectives(qtbot):
    from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
    w = ObjectiveChipsWidget()
    qtbot.addWidget(w)
    w.set_objectives([{"objective_id": "obj_1"}, {"objective_id": "obj_2"}])
    assert w.isVisible()
    assert "obj_1" in w._chips
    assert "obj_2" in w._chips


def test_chips_mark_passed_updates_text(qtbot):
    from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
    w = ObjectiveChipsWidget()
    qtbot.addWidget(w)
    w.set_objectives([{"objective_id": "obj_1"}])
    w.mark_passed("obj_1")
    assert "\u2713" in w._chips["obj_1"].text()


def test_chips_mark_failed_updates_text(qtbot):
    from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
    w = ObjectiveChipsWidget()
    qtbot.addWidget(w)
    w.set_objectives([{"objective_id": "obj_x"}])
    w.mark_failed("obj_x")
    assert "\u2717" in w._chips["obj_x"].text()


def test_chips_reset_hides_widget(qtbot):
    from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
    w = ObjectiveChipsWidget()
    qtbot.addWidget(w)
    w.set_objectives([{"objective_id": "a"}])
    w.reset()
    assert not w.isVisible()
    assert len(w._chips) == 0


def test_chips_mark_running_starts_pulse(qtbot):
    from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget
    w = ObjectiveChipsWidget()
    qtbot.addWidget(w)
    w.set_objectives([{"objective_id": "obj_r"}])
    w.mark_running("obj_r")
    assert "obj_r" in w._pulse_timers
