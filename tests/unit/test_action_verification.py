"""Action-tier verification (C5 generalization) — mocked sensors, no real I/O/LLM."""
from __future__ import annotations

import time

import pytest

from trinity_pilot.workers.action_verification import ActionTier, VerifyResult, verify_action

# ---------------------------------------------------------------------------
# Unregistered action — no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unregistered_action_returns_none():
    result = await verify_action("some_unknown_tool", {})
    assert result is None


# ---------------------------------------------------------------------------
# Deterministic tier — write_file / run_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_file_deterministic_pass_no_failures():
    result = await verify_action("write_file", {"write_file_failures": []})
    assert result == VerifyResult(
        tier=ActionTier.DETERMINISTIC, detail="write_file verified: file exists on disk", ok=True
    )


@pytest.mark.asyncio
async def test_write_file_deterministic_fail_when_failures_present():
    evidence = {"write_file_failures": [{"path": "C:/x.txt", "error": "disk full"}]}
    result = await verify_action("write_file", evidence)
    assert result.tier is ActionTier.DETERMINISTIC
    assert result.ok is False
    assert "disk full" in result.detail


@pytest.mark.asyncio
async def test_run_command_deterministic_pass_on_zero_exit():
    result = await verify_action("run_command", {"exit_code": 0})
    assert result.ok is True


@pytest.mark.asyncio
async def test_run_command_deterministic_fail_on_nonzero_exit():
    result = await verify_action("run_command", {"exit_code": 1})
    assert result.ok is False


@pytest.mark.asyncio
async def test_deterministic_tier_never_calls_sensor_check_or_sensor_read():
    calls = {"check": 0, "read": 0}

    async def sensor_check():
        calls["check"] += 1
        return True

    async def sensor_read():
        calls["read"] += 1
        return "should not be called"

    await verify_action(
        "write_file",
        {"write_file_failures": []},
        sensor_check=sensor_check,
        sensor_read=sensor_read,
    )
    assert calls == {"check": 0, "read": 0}


# ---------------------------------------------------------------------------
# Eventually-consistent tier — launch_app / navigate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eventually_tier_no_sensor_check_returns_none():
    result = await verify_action("launch_app", {})
    assert result is None


@pytest.mark.asyncio
async def test_eventually_tier_succeeds_immediately():
    async def sensor_check():
        return True

    result = await verify_action("launch_app", {}, sensor_check=sensor_check, deadline_seconds=1.0)
    assert result.tier is ActionTier.EVENTUALLY_CONSISTENT
    assert result.ok is True
    assert "confirmed" in result.detail


@pytest.mark.asyncio
async def test_eventually_tier_polls_then_succeeds():
    responses = iter([False, False, True])

    async def sensor_check():
        return next(responses)

    result = await verify_action("navigate", {}, sensor_check=sensor_check, deadline_seconds=5.0)
    assert result.ok is True


@pytest.mark.asyncio
async def test_eventually_tier_times_out_within_bounded_deadline():
    async def sensor_check():
        return False

    start = time.monotonic()
    result = await verify_action("navigate", {}, sensor_check=sensor_check, deadline_seconds=0.3)
    elapsed = time.monotonic() - start

    assert result.ok is False
    assert "not confirmed" in result.detail
    # Bounded — must not hang past roughly the deadline (generous margin for
    # backoff scheduling jitter, but proves it's not an infinite loop).
    assert elapsed < 3.0


@pytest.mark.asyncio
async def test_eventually_tier_sensor_check_exception_treated_as_not_confirmed():
    async def sensor_check():
        raise RuntimeError("sensor unavailable")

    result = await verify_action("launch_app", {}, sensor_check=sensor_check, deadline_seconds=0.3)
    assert result.ok is False


# ---------------------------------------------------------------------------
# LLM-grounded tier — click_button / type_text (no LLM call made here)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_grounded_tier_no_sensor_read_returns_none():
    result = await verify_action("click_button", {})
    assert result is None


@pytest.mark.asyncio
async def test_llm_grounded_tier_folds_sensor_text_no_judgment_made():
    async def sensor_read():
        return "UIA text after click: dialog closed"

    result = await verify_action("click_button", {}, sensor_read=sensor_read)
    assert result.tier is ActionTier.LLM_GROUNDED
    assert result.detail == "UIA text after click: dialog closed"
    assert result.ok is None  # left for the acting LLM to judge, not decided here


@pytest.mark.asyncio
async def test_llm_grounded_tier_sensor_read_exception_captured_in_detail():
    async def sensor_read():
        raise RuntimeError("UIA dump failed")

    result = await verify_action("type_text", {}, sensor_read=sensor_read)
    assert result.ok is None
    assert "UIA dump failed" in result.detail


@pytest.mark.asyncio
async def test_nothing_persisted_to_evidence_across_all_tiers():
    evidence = {"write_file_failures": [], "exit_code": 0}
    before = dict(evidence)

    await verify_action("write_file", evidence)
    await verify_action("run_command", evidence)
    await verify_action("launch_app", evidence, sensor_check=lambda: _true())
    await verify_action("click_button", evidence, sensor_read=lambda: _text())

    assert evidence == before


async def _true() -> bool:
    return True


async def _text() -> str:
    return "some sensor text"
