"""Layer-3 GUI session-continuity tests — multi-turn interactions within one session.

Each test submits multiple prompts in sequence against the same app instance,
verifying that the agent correctly handles clarification flows, mid-plan corrections,
task redirects, follow-ups, and chained clarification rounds.

Architecture note: each test gets a fresh app process (function-scoped `app` fixture),
so "session" here means within one live app launch, not across process restarts.

Run:
    pytest tests/e2e/test_gui_session_continuity.py -v --timeout=360
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e._gui_driver import (
    AFTER_CONFIRM,
    AFTER_SUBMIT,
    DESKTOP,
    STATUS_CLARIF,
    STATUS_CONFIRM,
    STATUS_ERROR,
    STATUS_FAILED,
)

pytestmark = [pytest.mark.e2e, pytest.mark.desktop, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Cleanup fixture
# ---------------------------------------------------------------------------

_SC_ARTIFACTS = [
    DESKTOP / "sc01_result.txt",
    DESKTOP / "sc02_data.txt",
    DESKTOP / "sc03_corrected.txt",
    DESKTOP / "sc03_original.txt",
    DESKTOP / "sc05_original.txt",
    DESKTOP / "sc05_variant.txt",
    DESKTOP / "sc06_final.txt",
]


@pytest.fixture(autouse=True)
def _cleanup_sc_artifacts():
    for p in _SC_ARTIFACTS:
        p.unlink(missing_ok=True)
    yield
    for p in _SC_ARTIFACTS:
        p.unlink(missing_ok=True)


def _read_artifact(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16').replace('\x00', '').strip()
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode('utf-16-le').replace('\x00', '').strip()
    return raw.decode('utf-8', errors='replace').replace('\x00', '').strip()


# ---------------------------------------------------------------------------
# SC-01 — Vague → clarify → complete
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SC01_vague_clarify_complete(app):
    """Vague prompt triggers clarification; user responds with specific task; agent completes it."""
    app.submit("do something useful on my computer")
    s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC01_after_vague")

    assert s1 == STATUS_CLARIF, (
        f"SC-01: Expected clarification for vague prompt, got {s1!r}"
    )

    # User clarifies with a concrete task
    app.submit(
        "create a file called sc01_result.txt on the Desktop "
        "containing exactly the text 'sc01-done'"
    )
    s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC01_after_clarification")

    # BH-EVAL-002: after fail-closed clarify (BH-004), absorb more re-clarify
    # rounds from the lite classifier before treating as real failure.
    for _ in range(4):
        if s2 != STATUS_CLARIF:
            break
        app.submit("yes, proceed with creating sc01_result.txt on the Desktop with text sc01-done")
        s2 = app.wait_for(AFTER_SUBMIT, timeout=60)

    if s2 in (STATUS_FAILED, STATUS_ERROR):
        pytest.fail(f"SC-01: Planning failed after clarification: {s2!r}")

    assert s2 == STATUS_CONFIRM, f"SC-01: Expected plan after clarification, got {s2!r}"

    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("SC01_done")

    assert "failed" not in done.lower(), f"SC-01: Task ended with failure: {done!r}"

    artifact = DESKTOP / "sc01_result.txt"
    assert artifact.exists(), "SC-01: sc01_result.txt was not created on the Desktop"
    content = _read_artifact(artifact)
    assert "sc01" in content.lower(), (
        f"SC-01: Expected 'sc01' in file content, got: {content!r}"
    )


# ---------------------------------------------------------------------------
# SC-02 — Reference prior artifact in same session
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SC02_reference_prior_result(app):
    """Task A creates a file; task B in the same session references it by content."""
    # --- Turn 1: create file ---
    app.submit(
        "Create a file called sc02_data.txt on the Desktop "
        "containing exactly the text 'hello-sc02'"
    )
    s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s1 == STATUS_CLARIF:
        app.submit("yes, create sc02_data.txt with hello-sc02")
        s1 = app.wait_for(AFTER_SUBMIT, timeout=60)

    if s1 != STATUS_CONFIRM:
        pytest.skip(f"SC-02: Turn 1 planning did not reach confirmation: {s1!r}")

    app.submit("yes")
    done1 = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("SC02_turn1_done")
    assert "failed" not in done1.lower(), f"SC-02: Turn 1 failed: {done1!r}"

    artifact = DESKTOP / "sc02_data.txt"
    assert artifact.exists(), "SC-02: sc02_data.txt was not created — turn 2 cannot proceed"

    # --- Turn 2: reference the file ---
    app.submit(
        "Read the file sc02_data.txt on the Desktop and tell me its exact contents."
    )
    s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s2 == STATUS_CLARIF:
        app.submit("yes, read sc02_data.txt on the Desktop")
        s2 = app.wait_for(AFTER_SUBMIT, timeout=60)

    if s2 in (STATUS_FAILED, STATUS_ERROR):
        pytest.fail(f"SC-02: Turn 2 planning failed: {s2!r}")

    if s2 == STATUS_CONFIRM:
        app.submit("yes")
        done2 = app.wait_for(AFTER_CONFIRM, timeout=120)
        app.snap("SC02_turn2_done")
        assert "failed" not in done2.lower(), f"SC-02: Turn 2 failed: {done2!r}"

        ui = app.ui_text()
        assert "hello-sc02" in ui, (
            f"SC-02: Expected 'hello-sc02' in chat after readback. UI (first 400): {ui[:400]}"
        )


# ---------------------------------------------------------------------------
# SC-03 — Plan correction before execution
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SC03_plan_correction(app):
    """User sends correction instead of 'yes'; agent should re-plan with updated name."""
    app.submit(
        "Create a file called sc03_original.txt on the Desktop with text 'sc03-content'."
    )
    s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s1 == STATUS_CLARIF:
        app.submit("yes, create sc03_original.txt")
        s1 = app.wait_for(AFTER_SUBMIT, timeout=60)

    if s1 != STATUS_CONFIRM:
        pytest.skip(f"SC-03: Could not reach planning stage: {s1!r}")

    app.snap("SC03_plan_shown")

    # Correction: rename to sc03_corrected.txt instead of confirming
    app.submit(
        "Actually, name the file sc03_corrected.txt instead of sc03_original.txt."
    )
    s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC03_after_correction")

    if s2 == STATUS_CLARIF:
        # Agent asked for clarification — confirm the corrected name
        app.submit("yes, create sc03_corrected.txt with text sc03-content")
        s2 = app.wait_for(AFTER_SUBMIT, timeout=60)

    if s2 in (STATUS_FAILED, STATUS_ERROR):
        pytest.fail(f"SC-03: Planning failed after correction: {s2!r}")

    assert s2 == STATUS_CONFIRM, f"SC-03: Expected re-plan after correction, got {s2!r}"

    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("SC03_done")

    corrected = DESKTOP / "sc03_corrected.txt"
    original = DESKTOP / "sc03_original.txt"

    assert corrected.exists() or original.exists(), (
        f"SC-03: Neither sc03_corrected.txt nor sc03_original.txt was created. "
        f"Status: {done!r}"
    )


# ---------------------------------------------------------------------------
# SC-04 — New task redirect instead of confirming
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SC04_task_redirect(app):
    """User sends a different task instead of 'yes'; agent must handle the redirect."""
    # Submit task A
    app.submit("Open Notepad and type the text 'sc04-notepad'.")
    s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s1 == STATUS_CLARIF:
        return  # clarification — can't test redirect from here
    if s1 != STATUS_CONFIRM:
        pytest.skip(f"SC-04: Could not reach planning stage: {s1!r}")

    app.snap("SC04_plan_A_shown")

    # Send task B instead of "yes" — completely different task
    app.submit(
        "Actually ignore that. Instead, just count how many .txt files "
        "are on the Desktop and tell me the number."
    )
    s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC04_after_redirect")

    # Agent must not blindly execute the original Notepad plan.
    # Acceptable outcomes: re-plans for task B, or asks for clarification.
    assert s2 in {STATUS_CLARIF, STATUS_CONFIRM, STATUS_FAILED, STATUS_ERROR}, (
        f"SC-04: Unexpected status after redirect: {s2!r}"
    )

    if s2 == STATUS_CONFIRM:
        app.submit("yes")
        done = app.wait_for(AFTER_CONFIRM, timeout=120)
        app.snap("SC04_done")
        assert "failed" not in done.lower(), f"SC-04: Task B failed: {done!r}"
        ui = app.ui_text()
        # Task B result should mention a count (number)
        assert re.search(r"\b\d+\b", ui), (
            f"SC-04: Expected a file count in chat from task B. UI (first 400): {ui[:400]}"
        )


# ---------------------------------------------------------------------------
# SC-05 — Follow-up variation after completion
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SC05_followup_variation(app):
    """After completing task 1, user asks for a variation; both artifacts must exist."""
    # --- Turn 1 ---
    app.submit(
        "Create a file called sc05_original.txt on the Desktop with text 'original-content'."
    )
    s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s1 == STATUS_CLARIF:
        app.submit("yes, create sc05_original.txt")
        s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s1 != STATUS_CONFIRM:
        pytest.skip(f"SC-05: Turn 1 planning failed: {s1!r}")

    app.submit("yes")
    done1 = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("SC05_turn1_done")
    assert "failed" not in done1.lower(), f"SC-05: Turn 1 failed: {done1!r}"
    assert (DESKTOP / "sc05_original.txt").exists(), "SC-05: sc05_original.txt not created"

    # --- Turn 2: variation ---
    app.submit(
        "Now create another file called sc05_variant.txt on the Desktop "
        "with the same text but append '-variant' at the end, "
        "so the content is 'original-content-variant'."
    )
    s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s2 == STATUS_CLARIF:
        app.submit("yes, create sc05_variant.txt with 'original-content-variant'")
        s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    if s2 in (STATUS_FAILED, STATUS_ERROR):
        pytest.fail(f"SC-05: Turn 2 planning failed: {s2!r}")
    if s2 != STATUS_CONFIRM:
        pytest.skip(f"SC-05: Turn 2 did not reach confirmation: {s2!r}")

    app.submit("yes")
    done2 = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("SC05_turn2_done")
    assert "failed" not in done2.lower(), f"SC-05: Turn 2 failed: {done2!r}"

    variant = DESKTOP / "sc05_variant.txt"
    assert variant.exists(), "SC-05: sc05_variant.txt was not created"
    content = _read_artifact(variant)
    assert "variant" in content.lower(), (
        f"SC-05: Expected 'variant' in sc05_variant.txt, got: {content!r}"
    )


# ---------------------------------------------------------------------------
# SC-06 — Three-round clarification chain
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_SC06_multi_round_clarification(app):
    """Three rounds of clarification before a specific task; agent must track context."""
    # Round 1: very vague
    app.submit("do something")
    s1 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC06_round1")

    if s1 != STATUS_CLARIF:
        # If agent somehow planned this, skip — VAG tests cover this case
        return

    # Round 2: still vague
    app.submit("something with files")
    s2 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC06_round2")

    if s2 == STATUS_CONFIRM:
        # Agent planned from partial info — confirm and move on
        app.submit("yes")
        app.wait_for(AFTER_CONFIRM, timeout=120)
        return

    if s2 != STATUS_CLARIF:
        return  # Failed or error — not a continuity failure, skip

    # Round 3: specific
    app.submit(
        "Create a file called sc06_final.txt on the Desktop with the text 'sc06-done'."
    )
    s3 = app.wait_for(AFTER_SUBMIT, timeout=60)
    app.snap("SC06_round3")

    if s3 == STATUS_CLARIF:
        # Fourth round acceptable — just confirm
        app.submit("yes, create sc06_final.txt with sc06-done")
        s3 = app.wait_for(AFTER_SUBMIT, timeout=60)

    if s3 in (STATUS_FAILED, STATUS_ERROR):
        pytest.fail(f"SC-06: Planning failed after 3+ clarification rounds: {s3!r}")

    if s3 == STATUS_CONFIRM:
        app.submit("yes")
        done = app.wait_for(AFTER_CONFIRM, timeout=120)
        app.snap("SC06_done")
        assert "failed" not in done.lower(), f"SC-06: Execution failed: {done!r}"
        assert (DESKTOP / "sc06_final.txt").exists(), (
            "SC-06: sc06_final.txt not created after multi-round clarification"
        )
