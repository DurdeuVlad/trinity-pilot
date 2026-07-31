"""Real tests for the unified take_screenshot tool.

Tests three levels:
1. capture_screenshot() function directly — all three modes.
2. DesktopWorker dispatching take_screenshot via _dispatch_tool.
3. DesktopWorker full ReAct loop with a screenshot-only goal.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

pytestmark = pytest.mark.real


def _is_valid_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


# ---------------------------------------------------------------------------
# Level 1: direct capture_screenshot() function
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_capture_screen_primary():
    from trinity_pilot.tools.screenshot import capture_screenshot
    img_bytes, desc = capture_screenshot(mode="screen", screen_index=0)
    assert len(img_bytes) > 1000, "JPEG too small — likely empty"
    assert _is_valid_jpeg(img_bytes), "Not a valid JPEG"
    assert "primary" in desc or "screen" in desc


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_capture_all_screens():
    from trinity_pilot.tools.screenshot import capture_screenshot
    img_bytes, desc = capture_screenshot(mode="all_screens")
    assert len(img_bytes) > 1000
    assert _is_valid_jpeg(img_bytes)
    assert "screen" in desc


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_capture_app_window_fallback_on_no_match():
    """app mode with a non-existent title should fall back gracefully."""
    from trinity_pilot.tools.screenshot import capture_screenshot
    img_bytes, desc = capture_screenshot(mode="app", app_title="ZZZNoSuchWindowXXX")
    assert len(img_bytes) > 1000
    assert _is_valid_jpeg(img_bytes)


# ---------------------------------------------------------------------------
# Level 2: DesktopWorker._dispatch_tool dispatches take_screenshot
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
async def test_desktop_worker_dispatch_take_screenshot():
    """Call _dispatch_tool('take_screenshot', ...) directly — no LLM involved."""
    from trinity_pilot.workers.desktop_worker import DesktopWorker
    worker = DesktopWorker()
    evidence: dict = {"action_log": []}
    result = await worker._dispatch_tool("screenshot", {}, evidence)
    assert isinstance(result, tuple), "Expected (str, bytes) tuple"
    text, img_bytes = result
    assert "Screenshot captured" in text
    assert _is_valid_jpeg(img_bytes)
    assert evidence.get("screenshot"), "screenshot not stored in evidence"
    b64 = evidence["screenshot"]
    decoded = base64.b64decode(b64)
    assert _is_valid_jpeg(decoded)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
async def test_desktop_worker_dispatch_take_screenshot_all_screens():
    from trinity_pilot.workers.desktop_worker import DesktopWorker
    worker = DesktopWorker()
    evidence: dict = {"action_log": []}
    result = await worker._dispatch_tool("screenshot", {"mode": "all_screens"}, evidence)
    assert isinstance(result, tuple)
    text, img_bytes = result
    assert "all screens" in text
    assert _is_valid_jpeg(img_bytes)


# ---------------------------------------------------------------------------
# Level 3: Full ReAct loop — agent instructed to take a screenshot and finish
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
async def test_desktop_worker_react_screenshot_goal(gemini_api_key: str):
    """Full DesktopWorker ReAct loop: goal is to take a screenshot and report what is visible."""
    del gemini_api_key
    from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
    from trinity_pilot.workers.desktop_worker import DesktopWorker

    spec = ObjectiveSpec(
        objective_id="real-screenshot-react",
        goal=(
            "Take a screenshot of the entire desktop screen using take_screenshot. "
            "Then call finish with status='success' and a brief description of what you see."
        ),
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_screenshot"],
        risk_class=RiskClass.LOW,
        preconditions=["Windows interactive desktop", "GEMINI_API_KEY set"],
        success_tests=["screenshot captured"],
        evidence_bundle=["screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
        metadata={"timeout_seconds": 60, "max_agent_steps": 4},
    )

    worker = DesktopWorker()
    evidence = await worker.execute(spec)

    assert evidence["domain"] == "desktop"
    assert evidence["worker_result_status"] == "success"
    assert evidence.get("screenshot"), "No screenshot in evidence"
    decoded = base64.b64decode(evidence["screenshot"])
    assert _is_valid_jpeg(decoded), "Screenshot in evidence is not a valid JPEG"
    assert any("Screenshot captured" in entry for entry in evidence["action_log"]), (
        f"action_log missing screenshot entry: {evidence['action_log']}"
    )
