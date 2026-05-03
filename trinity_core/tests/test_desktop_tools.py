"""Unit and integration tests for desktop tool additions:
- DesktopListWindowsTool
- DesktopGetFocusedWindowTool
- was_existing field in DesktopOpenAppTool
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from trinity_core.tools.desktop_tools import (
    DesktopGetFocusedWindowTool,
    DesktopHotkeyTool,
    DesktopListWindowsTool,
    DesktopOpenAppTool,
    DesktopTypeTool,
    DesktopWaitForTextTool,
    _DesktopState,
    build_desktop_tools,
)


# ---------------------------------------------------------------------------
# DesktopListWindowsTool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_windows_returns_titles():
    tool = DesktopListWindowsTool()
    with patch("trinity_core.tools.desktop_tools.list_open_windows", return_value=["Notepad", "Calculator", ""]):
        result = await tool.execute()
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert "Notepad" in payload["windows"]
    assert "Calculator" in payload["windows"]
    assert "" not in payload["windows"]


@pytest.mark.asyncio
async def test_list_windows_caps_at_20():
    tool = DesktopListWindowsTool()
    many = [f"Window {i}" for i in range(30)]
    with patch("trinity_core.tools.desktop_tools.list_open_windows", return_value=many):
        result = await tool.execute()
    assert result.status == "success"
    payload = json.loads(result.output)
    assert len(payload["windows"]) <= 20


@pytest.mark.asyncio
async def test_list_windows_empty_desktop():
    tool = DesktopListWindowsTool()
    with patch("trinity_core.tools.desktop_tools.list_open_windows", return_value=[]):
        result = await tool.execute()
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["windows"] == []


# ---------------------------------------------------------------------------
# DesktopGetFocusedWindowTool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_focused_window_success():
    tool = DesktopGetFocusedWindowTool()
    with patch("trinity_core.tools.desktop_tools.get_focused_window", return_value="Notepad"):
        result = await tool.execute()
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["title"] == "Notepad"


@pytest.mark.asyncio
async def test_get_focused_window_error():
    tool = DesktopGetFocusedWindowTool()
    with patch("trinity_core.tools.desktop_tools.get_focused_window", return_value="ERROR: No focused window found"):
        result = await tool.execute()
    assert result.status == "error"
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert "No focused window found" in payload["message"]


# ---------------------------------------------------------------------------
# DesktopOpenAppTool — was_existing
# ---------------------------------------------------------------------------

def _make_open_app_tool() -> DesktopOpenAppTool:
    return DesktopOpenAppTool(_DesktopState())


@pytest.mark.asyncio
async def test_open_app_was_existing_true():
    tool = _make_open_app_tool()
    with (
        patch("trinity_core.tools.desktop_tools.list_open_windows", return_value=["Untitled - Notepad"]),
        patch("trinity_core.tools.desktop_tools.launch_app", return_value="Untitled - Notepad"),
        patch("trinity_core.tools.desktop_tools._wait_for_matching_window", return_value="Untitled - Notepad"),
        patch("trinity_core.tools.desktop_tools.focus_window", return_value="OK"),
    ):
        result = await tool.execute(app_name="notepad")
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["was_existing"] is True


@pytest.mark.asyncio
async def test_open_app_focuses_existing_metacharacter_title_without_changing_was_existing():
    tool = _make_open_app_tool()
    title = "026-04-27Attendees- Agenda- Action * - Notepad"
    with (
        patch("trinity_core.tools.desktop_tools.list_open_windows", return_value=[title]),
        patch("trinity_core.tools.desktop_tools.launch_app", return_value=title),
        patch("trinity_core.tools.desktop_tools._wait_for_matching_window", return_value=title),
        patch("trinity_core.tools.desktop_tools.focus_window", return_value="OK") as focus_mock,
    ):
        result = await tool.execute(app_name="notepad")
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["was_existing"] is True
    assert payload["active_window"] == title
    focus_mock.assert_called_once_with(title)


@pytest.mark.asyncio
async def test_open_app_was_existing_false():
    tool = _make_open_app_tool()
    call_count = 0

    def _list_windows_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ["Calculator"]
        return ["Calculator", "Untitled - Notepad"]

    with (
        patch("trinity_core.tools.desktop_tools.list_open_windows", side_effect=_list_windows_side_effect),
        patch("trinity_core.tools.desktop_tools.launch_app", return_value="Untitled - Notepad"),
        patch("trinity_core.tools.desktop_tools._wait_for_matching_window", return_value="Untitled - Notepad"),
        patch("trinity_core.tools.desktop_tools.focus_window", return_value="OK"),
    ):
        result = await tool.execute(app_name="notepad")
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["was_existing"] is False


# ---------------------------------------------------------------------------
# build_desktop_tools — registration
# ---------------------------------------------------------------------------

def test_build_desktop_tools_count():
    tools = build_desktop_tools()
    assert len(tools) == 13


def test_build_desktop_tools_keys():
    tools = build_desktop_tools()
    assert "list_windows" in tools
    assert "get_focused_window" in tools
    assert "open_app" in tools
    assert "focus" in tools
    assert "click" in tools
    assert "type" in tools
    assert "hotkey" in tools
    assert "paste" in tools
    assert "list_controls" in tools


@pytest.mark.asyncio
async def test_type_targets_active_app():
    state = _DesktopState()
    state.active_app = "Notepad"
    tool = DesktopTypeTool(state)
    with patch("trinity_core.tools.desktop_tools.type_text", return_value="OK") as type_mock:
        result = await tool.execute(text="hello")
    assert result.status == "success"
    type_mock.assert_called_once_with("hello", "Notepad")


@pytest.mark.asyncio
async def test_type_routes_shortcut_syntax_to_hotkey():
    state = _DesktopState()
    state.active_app = "Notepad"
    tool = DesktopTypeTool(state)
    with patch("trinity_core.tools.desktop_tools.send_hotkey", return_value="OK") as hotkey_mock:
        result = await tool.execute(text="^s")
    assert result.status == "success"
    payload = json.loads(result.output)
    assert payload["routed_to_hotkey"] is True
    hotkey_mock.assert_called_once_with("^s", "Notepad")


@pytest.mark.asyncio
async def test_hotkey_targets_active_app():
    state = _DesktopState()
    state.active_app = "Notepad"
    tool = DesktopHotkeyTool(state)
    with patch("trinity_core.tools.desktop_tools.send_hotkey", return_value="OK") as hotkey_mock:
        result = await tool.execute(keys="Ctrl+S")
    assert result.status == "success"
    hotkey_mock.assert_called_once_with("Ctrl+S", "Notepad")


@pytest.mark.asyncio
async def test_wait_for_text_uses_successful_type_evidence():
    state = _DesktopState()
    state.active_app = "Notepad"
    type_tool = DesktopTypeTool(state)
    wait_tool = DesktopWaitForTextTool(state)
    with patch("trinity_core.tools.desktop_tools.type_text", return_value="OK"):
        type_result = await type_tool.execute(app="Notepad", text="Meeting Notes - 2026-04-27\n")
    wait_result = await wait_tool.execute(app="Notepad", text="Meeting Notes - 2026-04-27", timeout=0.01)
    assert type_result.status == "success"
    assert wait_result.status == "success"
    payload = json.loads(wait_result.output)
    assert payload["evidence"] == "typed_text_cache"
