"""Story 2 tests: bubble_renderer color tables + execution_row.

AC-03: Light mode bubble colors correct.
AC-04: Dark mode bubble colors correct.
AC-12: No inline hex literals in function bodies.
AC-13: execution_row returns valid HTML for all four status values.
"""
from __future__ import annotations

import re
import pathlib

from trinity_pilot.ui.bubble_renderer import (
    _DARK,
    _LIGHT,
    ai_bubble,
    execution_row,
    objectives_card,
    summary_bubble,
    system_note,
    user_bubble,
)


# ---------------------------------------------------------------------------
# Color dict presence
# ---------------------------------------------------------------------------


def test_light_dict_has_required_keys():
    required = {
        "user_bg", "user_fg", "ai_bg", "ai_fg", "ai_accent",
        "card_bg", "card_border", "header_fg", "divider", "desc_fg", "obj_fg",
        "summary_ok_bg", "summary_cancel_bg", "summary_fail_bg", "summary_fg",
        "system_fg",
    }
    assert required.issubset(_LIGHT.keys()), f"Missing keys: {required - _LIGHT.keys()}"


def test_dark_dict_has_same_keys_as_light():
    assert set(_LIGHT.keys()) == set(_DARK.keys()), (
        f"Key mismatch: only in LIGHT={_LIGHT.keys()-_DARK.keys()}, "
        f"only in DARK={_DARK.keys()-_LIGHT.keys()}"
    )


def test_light_and_dark_values_differ():
    assert any(_LIGHT[k] != _DARK[k] for k in _LIGHT), (
        "All keys have identical values in _LIGHT and _DARK"
    )


# ---------------------------------------------------------------------------
# No inline hex in function bodies
# ---------------------------------------------------------------------------


def test_no_inline_hex_in_function_bodies():
    src_path = pathlib.Path(__file__).parents[2] / "trinity_pilot" / "ui" / "bubble_renderer.py"
    src = src_path.read_text(encoding="utf-8")
    # Find last occurrence of _DARK dict definition; everything after is function bodies
    dark_idx = src.rindex("_DARK")
    # Move past the closing brace of the _DARK dict block
    after_dark_block = src[dark_idx:]
    # Find end of dict (closing brace at column 0)
    brace_end = after_dark_block.index("}\n") + 2
    after_dicts = after_dark_block[brace_end:]

    hex_pattern = re.compile(r'(?<!\w)#[0-9A-Fa-f]{6}(?!\w)')
    inline_hits = []
    for line in after_dicts.splitlines():
        stripped = line.strip()
        # skip comment lines and lines that are string keys in a dict
        if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
            continue
        if hex_pattern.search(line):
            inline_hits.append(line)
    assert inline_hits == [], f"Inline hex found in function bodies:\n" + "\n".join(inline_hits)


# ---------------------------------------------------------------------------
# user_bubble
# ---------------------------------------------------------------------------


def test_user_bubble_light_uses_light_bg():
    html = user_bubble("x", dark=False)
    assert _LIGHT["user_bg"] in html, f"Expected {_LIGHT['user_bg']} in light user_bubble"


def test_user_bubble_dark_uses_dark_bg():
    html = user_bubble("x", dark=True)
    assert _DARK["user_bg"] in html, f"Expected {_DARK['user_bg']} in dark user_bubble"


def test_user_bubble_still_right_aligned():
    assert "text-align:right" in user_bubble("x")


# ---------------------------------------------------------------------------
# ai_bubble
# ---------------------------------------------------------------------------


def test_ai_bubble_light_uses_light_bg():
    html = ai_bubble("x", dark=False)
    assert _LIGHT["ai_bg"] in html, f"Expected {_LIGHT['ai_bg']} in light ai_bubble"


def test_ai_bubble_dark_uses_dark_bg():
    html = ai_bubble("x", dark=True)
    assert _DARK["ai_bg"] in html, f"Expected {_DARK['ai_bg']} in dark ai_bubble"


def test_ai_bubble_still_left_aligned():
    assert "text-align:left" in ai_bubble("x")


# ---------------------------------------------------------------------------
# objectives_card
# ---------------------------------------------------------------------------


def test_objectives_card_still_contains_ids():
    specs = [{"objective_id": "obj_1", "domain": "cli"}]
    html = objectives_card(specs)
    assert "obj_1" in html


def test_objectives_card_light_uses_light_card_bg():
    specs = [{"objective_id": "x", "domain": "cli"}]
    html = objectives_card(specs, dark=False)
    assert _LIGHT["card_bg"] in html


def test_objectives_card_dark_uses_dark_card_bg():
    specs = [{"objective_id": "x", "domain": "cli"}]
    html = objectives_card(specs, dark=True)
    assert _DARK["card_bg"] in html


# ---------------------------------------------------------------------------
# summary_bubble
# ---------------------------------------------------------------------------


def test_summary_bubble_completed_still_works():
    html = summary_bubble(10.0, "completed", {"a": {"status": "passed"}})
    assert "✅" in html or "completed" in html.lower()


def test_summary_bubble_light_uses_light_ok_bg():
    html = summary_bubble(1.0, "completed", {"a": {"status": "passed"}}, dark=False)
    assert _LIGHT["summary_ok_bg"] in html


def test_summary_bubble_dark_uses_dark_ok_bg():
    html = summary_bubble(1.0, "completed", {"a": {"status": "passed"}}, dark=True)
    assert _DARK["summary_ok_bg"] in html


# ---------------------------------------------------------------------------
# system_note
# ---------------------------------------------------------------------------


def test_system_note_light_uses_light_fg():
    html = system_note("test", dark=False)
    assert _LIGHT["system_fg"] in html


def test_system_note_dark_uses_dark_fg():
    html = system_note("test", dark=True)
    assert _DARK["system_fg"] in html


# ---------------------------------------------------------------------------
# execution_row — AC-13
# ---------------------------------------------------------------------------


def test_execution_row_returns_nonempty_for_all_statuses():
    for status in ("running", "done", "failed", "pending"):
        result = execution_row("step-1", status, 0, False)
        assert isinstance(result, str) and len(result) > 0, f"Empty for status={status}"


def test_execution_row_contains_label():
    result = execution_row("my-step", "running", 0, False)
    assert "my-step" in result


def test_execution_row_contains_color():
    result = execution_row("step", "done", 0, False)
    assert re.search(r"#[0-9A-Fa-f]{6}", result), "No hex color in execution_row output"


def test_execution_row_indentation():
    result_0 = execution_row("s", "pending", 0, False)
    result_2 = execution_row("s", "pending", 2, False)
    # indent_level=2 => padding-left:32px
    assert "32px" in result_2 or "padding-left:32" in result_2
    # level 0 should have 0px or no padding-left:32
    assert "32px" not in result_0


def test_execution_row_dark_differs_from_light():
    light = execution_row("s", "running", 0, False)
    dark = execution_row("s", "running", 0, True)
    assert light != dark


def test_execution_row_no_exception_on_unknown_status():
    # Should not raise; fallback to pending style
    result = execution_row("s", "unknown_status", 0, False)
    assert isinstance(result, str)


def test_execution_row_done_contains_checkmark():
    result = execution_row("s", "done", 0, False)
    assert "✓" in result


def test_execution_row_failed_contains_cross():
    result = execution_row("s", "failed", 0, False)
    assert "✗" in result
