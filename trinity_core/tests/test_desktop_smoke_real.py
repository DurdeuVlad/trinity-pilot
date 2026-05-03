"""Real smoke tests for desktop tools — runs against actual Windows UI.
Requires interactive Windows session. No mocks.
"""
from __future__ import annotations

import asyncio
import platform
from typing import Any

import pytest

# Skip all tests if not on Windows
pytestmark = [
    pytest.mark.skipif(
        platform.system() != "Windows",
        reason="Real desktop tests require Windows",
    ),
    pytest.mark.smoke,
]


@pytest.mark.asyncio
async def test_list_windows_real():
    """Real test: list_windows returns actual window titles."""
    from trinity_core.tools.desktop_tools import DesktopListWindowsTool

    tool = DesktopListWindowsTool()
    result = await tool.execute()

    assert result.status == "success", f"Tool failed: {result.error}"

    import json

    payload = json.loads(result.output)
    windows = payload.get("windows", [])

    # Should return a list (may be empty if no visible windows)
    assert isinstance(windows, list), "windows should be a list"
    assert len(windows) <= 20, "should cap at 20 titles"
    # All items should be non-empty strings
    for w in windows:
        assert isinstance(w, str) and w.strip(), f"Empty title in list: {w!r}"

    print(f"\n[list_windows] Found {len(windows)} windows:")
    for w in windows[:5]:  # Print first 5
        print(f"  - {w}")


@pytest.mark.asyncio
async def test_get_focused_window_real():
    """Real test: get_focused_window returns actual focused window."""
    from trinity_core.tools.desktop_tools import DesktopGetFocusedWindowTool

    tool = DesktopGetFocusedWindowTool()
    result = await tool.execute()

    # This might fail if no window is focused (edge case), so we just verify structure
    import json

    payload = json.loads(result.output)

    if result.status == "success":
        title = payload.get("title", "")
        assert isinstance(title, str), "title should be a string"
        print(f"\n[get_focused_window] Current focus: {title}")
    else:
        # No focused window is acceptable in some states
        print(f"\n[get_focused_window] No focus (expected in some states): {payload}")


@pytest.mark.asyncio
async def test_open_app_was_existing_real():
    """Real test: open notepad, verify was_existing flag works."""
    from trinity_core.tools.desktop_tools import DesktopOpenAppTool, _DesktopState

    tool = DesktopOpenAppTool(_DesktopState())

    # First call — notepad likely not running, so was_existing should be false
    result = await tool.execute(app_name="notepad")

    import json

    assert result.status == "success", f"open_app failed: {result.error}"
    payload = json.loads(result.output)

    # Verify was_existing is present and is a boolean
    assert "was_existing" in payload, "was_existing field missing from payload"
    assert isinstance(payload["was_existing"], bool), "was_existing should be a boolean"

    # active_window should be present
    assert "active_window" in payload, "active_window missing"
    active_window = payload["active_window"]
    print(f"\n[open_app] was_existing={payload['was_existing']}, active_window={active_window}")

    # Second call — notepad is now running, was_existing should be true
    result2 = await tool.execute(app_name="notepad")
    assert result2.status == "success", f"second open_app failed: {result2.error}"

    payload2 = json.loads(result2.output)
    assert payload2.get("was_existing") is True, (
        f"Expected was_existing=True on second call, got {payload2.get('was_existing')}"
    )
    print(f"[open_app] Second call: was_existing={payload2['was_existing']}")


@pytest.mark.asyncio
async def test_list_windows_after_open_app():
    """Integration: open app then list windows to verify it's visible."""
    from trinity_core.tools.desktop_tools import (
        DesktopListWindowsTool,
        DesktopOpenAppTool,
        _DesktopState,
    )

    import json

    # Open notepad
    open_tool = DesktopOpenAppTool(_DesktopState())
    open_result = await open_tool.execute(app_name="notepad")
    assert open_result.status == "success"

    open_payload = json.loads(open_result.output)
    active_window = open_payload.get("active_window", "")
    print(f"\n[list+open] Opened: {active_window}")

    # List windows — should include notepad
    list_tool = DesktopListWindowsTool()
    list_result = await list_tool.execute()
    assert list_result.status == "success"

    list_payload = json.loads(list_result.output)
    windows = list_payload.get("windows", [])

    # Verify notepad is in the list (substring match)
    notepad_found = any("notepad" in w.lower() for w in windows)
    assert notepad_found, f"Notepad not found in windows list: {windows}"
    print(f"[list+open] Notepad found in {len(windows)} windows")
