"""Unit tests for ExecutionContext.get_latest_text_result()."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_UNIFIED = REPO_ROOT / "unified-app"
for _p in (str(REPO_ROOT), str(_UNIFIED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from orchestrator.execution_context import ExecutionContext  # noqa: E402


def _ctx(**kwargs: str) -> ExecutionContext:
    ctx = ExecutionContext(objective="test")
    ctx.accumulated_state.update(kwargs)
    return ctx


def test_returns_none_when_no_objectives() -> None:
    ctx = ExecutionContext(objective="test")
    assert ctx.get_latest_text_result() is None


def test_prefers_latest_text_override_when_present() -> None:
    ctx = _ctx(
        latest_text_result="Real copied paragraph",
        objective_1_desc="browse cats",
        objective_1_result="Generic success summary",
    )
    assert ctx.get_latest_text_result() == "Real copied paragraph"


def test_returns_single_objective_result() -> None:
    ctx = _ctx(objective_1_desc="browse cats", objective_1_result="The cat sat on the mat.")
    assert ctx.get_latest_text_result() == "The cat sat on the mat."


def test_returns_last_non_empty_when_multiple() -> None:
    ctx = _ctx(
        objective_1_desc="browse",
        objective_1_result="First result",
        objective_2_desc="browse more",
        objective_2_result="Second result",
    )
    assert ctx.get_latest_text_result() == "Second result"


def test_skips_whitespace_only_values() -> None:
    ctx = _ctx(
        objective_1_desc="step 1",
        objective_1_result="Actual content",
        objective_2_desc="step 2",
        objective_2_result="   ",
    )
    # Whitespace-only result should be skipped; previous non-empty wins.
    assert ctx.get_latest_text_result() == "Actual content"


def test_skips_non_string_values() -> None:
    ctx = ExecutionContext(objective="test")
    ctx.accumulated_state["objective_1_desc"] = "step 1"
    ctx.accumulated_state["objective_1_result"] = 42  # non-string
    ctx.accumulated_state["objective_2_desc"] = "step 2"
    ctx.accumulated_state["objective_2_result"] = "text output"
    assert ctx.get_latest_text_result() == "text output"


def test_returns_none_when_all_empty() -> None:
    ctx = _ctx(
        objective_1_desc="step 1",
        objective_1_result="",
        objective_2_desc="step 2",
        objective_2_result="",
    )
    assert ctx.get_latest_text_result() is None
