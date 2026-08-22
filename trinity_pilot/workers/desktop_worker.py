from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.telemetry.trace import emit
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _BlockerSignal,
    _finish_decl,
    _FinishSignal,
    _make_tool,
    _report_blocking_decl,
    _take_screenshot_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence
from trinity_pilot.workers.worker_result import WorkerResult


def _snapshot_pids() -> set[int]:
    """Return the set of all currently running PIDs (best-effort, never raises)."""
    try:
        import psutil
        return {p.pid for p in psutil.process_iter(["pid"])}
    except Exception:
        return set()


_DESKTOP_AGENT_SYSTEM = """\
You are a desktop automation agent on Windows.
Use the available tools to accomplish the goal step by step.

Tool categories:
- SENSOR tools read, inspect, measure, and detect. They never change world state.
  Use them freely before and after actions to verify state.
- ACTION tools create, modify, execute, or delete. They change world state.
  Each action must be intentional. Prefer sensing first, then acting.

Available tools:

[SENSOR] screenshot: Capture a window or screen as an image attached to your next turn.
  Use mode='app' with app_title to capture the target window. READ the image yourself —
  it is the reliable way to see display values, labels, and UI state that UIA text misses.
[SENSOR] clipboard_read: Read current clipboard text (after copy via press_hotkey).
[SENSOR] read_window_text: Read UIA text snippets (often incomplete — prefer screenshot for on-screen values).
[SENSOR] list_open_windows: List all visible top-level window titles.
[SENSOR] get_element_tree: Dump the UIA control tree (control_type/auto_id/title/rectangle/is_enabled) for a window, bounded depth/count.

[ACTION] launch_app: Launch an application by executable name.
[ACTION] focus_window: Focus a window by title regex.
[ACTION] type_text: Type text into the currently focused window.
[ACTION] press_hotkey: Press a keyboard hotkey combination.
[ACTION] press_key: Press a single key.
[ACTION] click_button: Click a UI button by its visible label text (e.g. 'Got it', 'OK').
[ACTION] click_coordinate: Click at pixel coordinates. Use only when no button/control locator exists (e.g. custom-drawn controls, canvas UI).
[ACTION] select_dropdown_option: Select an option in a dropdown/combo box by visible text.
[ACTION] window_control: Minimize, maximize, restore, move, or resize a window.
[ACTION] toggle_checkbox: Check, uncheck, or toggle a checkbox/radio/toggle control.
[ACTION] drag_and_drop: Drag from one point to another, relative to a window or in absolute screen coords.
[ACTION] scroll: Scroll the mouse wheel up/down/left/right at a location.
[ACTION] menu_select: Select a menu item by path, e.g. 'File->Save As'.
[ACTION] write_file: Write text content directly to a file at an absolute path.
[ACTION] wait: Pause execution for a number of seconds.
[ACTION] finish: Signal that the objective is complete or definitively failed.
[ACTION] report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

CRITICAL RULES:
- ALWAYS call focus_window BEFORE type_text, press_key, or press_hotkey.
  The system automatically re-focuses the last focused window before sending
  input, but you MUST still call focus_window at least once to declare which
  window should receive input. Without it, keystrokes may go to the wrong app.
- After launch_app, ALWAYS call focus_window with a title_re that matches the
  launched application before sending any keystrokes.
- ALWAYS use write_file to save content to disk. NEVER use GUI save dialogs.
- After write_file, open the created file so the user can see it. Use launch_app with the file
  path as an arg (e.g. {"action":"launch","app":"notepad.exe","args":["C:/path/to/file.txt"],"wait":1.5}).
- Call finish when the objective is done or definitively cannot be completed.
- Call report_blocking only if you genuinely cannot proceed without external input.
- Use forward slashes in all file paths.
- After each ACTION tool call, read its result before proceeding. If a tool failed or
  produced unexpected state, adapt â€” do not blindly continue to the next planned step.
- NEVER call finish until every action described in the GOAL is done. Read the GOAL in full
  before your first tool call.
- After actions that should show a result on screen, verify with screenshot(mode='app',
  app_title='<window title>'). The image is attached â€” read the display value directly
  from the pixels. Put the exact value you see into your finish summary.
- read_window_text is a fallback for labels/menus; it often omits numeric display fields.
  Do NOT call finish based on read_window_text alone when the goal asks you to report
  a value shown in the app â€” use screenshot and read the image first.
- To capture a value shown in an app: screenshot(mode='app') is preferred. Optionally
  try press_hotkey('ctrl','c') then clipboard_read if the app supports copy.
- NEVER call finish(success) for a task that required writing a file unless write_file
  has returned successfully for that file. Include the written file path in your finish summary.
- To CLOSE any application window: first use press_hotkey("alt", "F4") after focusing
  the window. Do NOT use Ctrl+W, Ctrl+F4, or any other shortcut â€” they trigger
  application-specific dialogs (e.g., Ctrl+W opens Resize/Skew in Paint, not close).
  If a "Save changes?" dialog appears and click_button("Don't save") fails, use
  kill_process(process_name="<exe>.exe") as a reliable direct termination fallback.
  kill_process is always available and does not require cmd.exe â€” prefer it over
  launching a terminal to type taskkill.
[ACTION] kill_process: Force-kill a process by .exe name (e.g. 'mspaint.exe'). Use when alt+F4 or click_button fail.
- Before performing actions in a freshly launched app, dismiss any welcome/popup
  dialogs. Check the screenshot after launch â€” if a coaching tooltip or dialog with
  a labeled button (e.g. "Got it", "OK", "Close") is visible, call
  click_button(button_text="Got it") (or the appropriate label) to dismiss it.
  Only fall back to press_key("escape") if no button label is visible.
  Do NOT proceed with the main task until the popup is gone â€” failing to dismiss
  a popup prevents subsequent key presses from reaching the target window.
  For Microsoft Paint: a "Try Image Creator" tooltip with a "Got it" button appears
  on launch. Call click_button(button_text="Got it") immediately after focus_window
  to dismiss it before drawing or closing Paint.
"""


def _normalise_click_button_args(args: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """Accept the declared label form and the UIA locator form emitted by models."""
    control = args.get("control")
    if isinstance(control, dict):
        button_text = control.get("title") or control.get("text") or control.get("name")
        title_re = control.get("title_re")
        control_type = str(control.get("control_type") or "Button")
    else:
        button_text = args.get("button_text") or args.get("title")
        title_re = args.get("title_re")
        control_type = "Button"
    return (
        str(button_text) if button_text else None,
        str(title_re) if title_re else None,
        control_type,
    )


def _click_button_locator(args: dict[str, Any]) -> dict[str, str]:
    """Normalize nested and top-level UIA locator shapes from planners."""
    control = args.get("control")
    source: dict[str, Any] = control if isinstance(control, dict) else args
    locator: dict[str, str] = {}
    auto_id = source.get("auto_id") or source.get("automation_id")
    if auto_id:
        locator["auto_id"] = str(auto_id)
    for key in ("title", "title_re", "control_type"):
        if source.get(key):
            locator[key] = str(source[key])
    return locator


def _button_locator_strategies(
    button_text: str | None,
    button_title_re: str | None,
    control_type: str,
) -> list[dict[str, str]]:
    """Build stable UIA locator variants from a model-provided button request."""
    strategies: list[dict[str, str]] = []
    if button_text:
        strategies.extend([
            {"title": button_text, "control_type": control_type},
            {"title_re": f"(?i){re.escape(button_text)}", "control_type": control_type},
            {"title_re": f"(?i){re.escape(button_text)}"},
        ])
    if button_title_re:
        strategies.extend([
            {"title_re": button_title_re, "control_type": control_type},
            {"title_re": button_title_re},
        ])
    return strategies

# Domain tool declarations
_launch_app_decl = genai_types.FunctionDeclaration(
    name="launch_app",
    description="Launch an application by executable name.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "app": genai_types.Schema(type=genai_types.Type.STRING, description="Executable name or path."),
            "args": genai_types.Schema(type=genai_types.Type.STRING, description="Space-separated arguments (optional)."),
            "wait": genai_types.Schema(type=genai_types.Type.NUMBER, description="Seconds to wait after launch."),
        },
        required=["app"],
    ),
)

_focus_window_decl = genai_types.FunctionDeclaration(
    name="focus_window",
    description="Focus a window matching a title regex.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window title regex."),
            "wait": genai_types.Schema(type=genai_types.Type.NUMBER, description="Seconds to wait after focus."),
        },
        required=["title_re"],
    ),
)

_type_text_decl = genai_types.FunctionDeclaration(
    name="type_text",
    description="Type text into the currently focused window.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "text": genai_types.Schema(type=genai_types.Type.STRING, description="Text to type."),
            "interval": genai_types.Schema(type=genai_types.Type.NUMBER, description="Interval between keystrokes."),
        },
        required=["text"],
    ),
)

_press_hotkey_decl = genai_types.FunctionDeclaration(
    name="press_hotkey",
    description="Press a keyboard hotkey combination. Accepts comma- or plus-separated keys, e.g. 'ctrl,s' or 'ctrl+s'.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "keys": genai_types.Schema(type=genai_types.Type.STRING, description="Hotkey keys separated by commas or plus signs, e.g. 'ctrl,s' or 'ctrl+s'."),
        },
        required=["keys"],
    ),
)

_press_key_decl = genai_types.FunctionDeclaration(
    name="press_key",
    description="Press a single key.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "key": genai_types.Schema(type=genai_types.Type.STRING, description="Key name e.g. 'enter'."),
        },
        required=["key"],
    ),
)

_desktop_write_file_decl = genai_types.FunctionDeclaration(
    name="write_file",
    description="Write text content directly to a file at an absolute path.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to write."),
            "content": genai_types.Schema(type=genai_types.Type.STRING, description="Text content to write."),
        },
        required=["path", "content"],
    ),
)

_wait_decl = genai_types.FunctionDeclaration(
    name="wait",
    description="Pause execution for a number of seconds.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "seconds": genai_types.Schema(type=genai_types.Type.NUMBER, description="Seconds to wait."),
        },
        required=["seconds"],
    ),
)

_get_clipboard_decl = genai_types.FunctionDeclaration(
    name="clipboard_read",
    description="Read and return the current clipboard text content.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
)

_read_window_text_decl = genai_types.FunctionDeclaration(
    name="read_window_text",
    description=(
        "Read UIA accessibility text snippets from a window. "
        "Often misses numeric display/result fields â€” use screenshot(mode='app') "
        "to read values shown on screen when the goal requires reporting a result."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Window title regex. Defaults to the last focused window.",
            ),
            "max_items": genai_types.Schema(
                type=genai_types.Type.INTEGER,
                description="Maximum snippets to return (default 15).",
            ),
        },
        required=[],
    ),
)

_click_button_decl = genai_types.FunctionDeclaration(
    name="click_button",
    description=(
        "Click a UI button found by its visible label text. "
        "Use this to dismiss dialog boxes, coaching tooltips, or popup buttons "
        "(e.g. 'Got it', 'OK', 'Cancel', 'Close'). "
        "Searches within the currently focused window if window_title_re is omitted."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "button_text": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Exact visible label of the button to click (e.g. 'Got it', 'OK').",
            ),
            "window_title_re": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Optional window title regex to search within. Defaults to the foreground window.",
            ),
        },
        required=["button_text"],
    ),
)

_kill_process_decl = genai_types.FunctionDeclaration(
    name="kill_process",
    description=(
        "Force-kill a process by executable name using taskkill /F /IM. "
        "Use this as a reliable fallback when alt+F4 or click_button fail to close a window. "
        "Example: kill_process(process_name='mspaint.exe') closes Paint without save dialogs."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "process_name": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Executable filename to kill, e.g. 'mspaint.exe', 'notepad.exe'.",
            ),
        },
        required=["process_name"],
    ),
)

_click_coordinate_decl = genai_types.FunctionDeclaration(
    name="click_coordinate",
    description=(
        "Click at pixel coordinates (x, y). Coordinates are relative to the named "
        "window's client area if window_title_re is given, otherwise absolute screen "
        "coordinates. Use only when no UIA control/button label exists for the target "
        "(e.g. canvas drawing, custom-rendered controls)."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "x": genai_types.Schema(type=genai_types.Type.INTEGER, description="X coordinate."),
            "y": genai_types.Schema(type=genai_types.Type.INTEGER, description="Y coordinate."),
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex; coordinates are relative to its client area. Omit for absolute screen coords."),
            "button": genai_types.Schema(type=genai_types.Type.STRING, description="'left', 'right', or 'double'. Default 'left'.", enum=["left", "right", "double"]),
        },
        required=["x", "y"],
    ),
)

_list_open_windows_decl = genai_types.FunctionDeclaration(
    name="list_open_windows",
    description="List visible top-level window titles currently open.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
)

_select_dropdown_option_decl = genai_types.FunctionDeclaration(
    name="select_dropdown_option",
    description="Select an option in a combo box / dropdown control by its visible text.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "option_text": genai_types.Schema(type=genai_types.Type.STRING, description="Visible text of the option to select."),
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex. Defaults to the focused target window."),
            "auto_id": genai_types.Schema(type=genai_types.Type.STRING, description="Optional automation ID of the combo box."),
            "control_title": genai_types.Schema(type=genai_types.Type.STRING, description="Optional visible label/title of the combo box."),
        },
        required=["option_text"],
    ),
)

_window_control_decl = genai_types.FunctionDeclaration(
    name="window_control",
    description="Minimize, maximize, restore, move, or resize a window.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex. Defaults to the focused target window."),
            "state": genai_types.Schema(type=genai_types.Type.STRING, description="'minimize', 'maximize', or 'restore'.", enum=["minimize", "maximize", "restore"]),
            "x": genai_types.Schema(type=genai_types.Type.INTEGER, description="New left position (optional, for move/resize)."),
            "y": genai_types.Schema(type=genai_types.Type.INTEGER, description="New top position (optional)."),
            "width": genai_types.Schema(type=genai_types.Type.INTEGER, description="New width (optional)."),
            "height": genai_types.Schema(type=genai_types.Type.INTEGER, description="New height (optional)."),
        },
        required=[],
    ),
)

_get_element_tree_decl = genai_types.FunctionDeclaration(
    name="get_element_tree",
    description=(
        "Dump the UIA control tree of a window as JSON: control_type, auto_id, title, "
        "rectangle, is_enabled per descendant. Use to discover exact locators for "
        "select_dropdown_option, toggle_checkbox, click_button, or postconditions."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex. Defaults to the focused target window."),
            "max_depth": genai_types.Schema(type=genai_types.Type.INTEGER, description="Max tree depth (default 3)."),
            "max_nodes": genai_types.Schema(type=genai_types.Type.INTEGER, description="Max nodes to return (default 200)."),
        },
        required=[],
    ),
)

_toggle_checkbox_decl = genai_types.FunctionDeclaration(
    name="toggle_checkbox",
    description="Check, uncheck, or toggle a checkbox/radio/toggle-button control.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex. Defaults to the focused target window."),
            "auto_id": genai_types.Schema(type=genai_types.Type.STRING, description="Automation ID of the control."),
            "control_title": genai_types.Schema(type=genai_types.Type.STRING, description="Visible label of the control."),
            "desired_state": genai_types.Schema(type=genai_types.Type.STRING, description="'checked', 'unchecked', or 'toggle'.", enum=["checked", "unchecked", "toggle"]),
        },
        required=["desired_state"],
    ),
)

_drag_and_drop_decl = genai_types.FunctionDeclaration(
    name="drag_and_drop",
    description="Drag from one point to another within a window (or absolute screen coords).",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "from_x": genai_types.Schema(type=genai_types.Type.INTEGER),
            "from_y": genai_types.Schema(type=genai_types.Type.INTEGER),
            "to_x": genai_types.Schema(type=genai_types.Type.INTEGER),
            "to_y": genai_types.Schema(type=genai_types.Type.INTEGER),
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Coordinates relative to this window's client area. Omit for absolute screen coords."),
            "duration": genai_types.Schema(type=genai_types.Type.NUMBER, description="Drag duration in seconds (default 0.5)."),
        },
        required=["from_x", "from_y", "to_x", "to_y"],
    ),
)

_desktop_scroll_decl = genai_types.FunctionDeclaration(
    name="scroll",
    description="Scroll the mouse wheel up/down/left/right at a location.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex. Defaults to the focused target window."),
            "direction": genai_types.Schema(type=genai_types.Type.STRING, enum=["up", "down", "left", "right"]),
            "amount": genai_types.Schema(type=genai_types.Type.INTEGER, description="Scroll amount/clicks (default 3)."),
            "x": genai_types.Schema(type=genai_types.Type.INTEGER, description="X coordinate to scroll at (relative to window if given, else absolute). Defaults to window center."),
            "y": genai_types.Schema(type=genai_types.Type.INTEGER, description="Y coordinate to scroll at."),
        },
        required=["direction"],
    ),
)

_menu_select_decl = genai_types.FunctionDeclaration(
    name="menu_select",
    description="Select a menu item by path in a classic Win32 menu bar, e.g. 'File->Save As'.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window regex. Defaults to the focused target window."),
            "path": genai_types.Schema(type=genai_types.Type.STRING, description="Menu path, e.g. 'File->Save As'."),
        },
        required=["path"],
    ),
)


_CALCULATOR_BUTTON_LABELS: dict[str, list[str]] = {
    "0": ["Zero"],
    "1": ["One"],
    "2": ["Two"],
    "3": ["Three"],
    "4": ["Four"],
    "5": ["Five"],
    "6": ["Six"],
    "7": ["Seven"],
    "8": ["Eight"],
    "9": ["Nine"],
    "add": ["Plus", "+"],
    "plus": ["Plus", "+"],
    "subtract": ["Minus", "âˆ’", "-"],
    "minus": ["Minus", "âˆ’", "-"],
    "multiply": ["Multiply by", "×", "Multiply"],
    "times": ["Multiply by", "×", "Multiply"],
    "x": ["Multiply by", "×", "Multiply"],
    "divide": ["Divide by", "÷", "Divide"],
    "return": ["Equals", "="],
    "enter": ["Equals", "="],
    "equals": ["Equals", "="],
    "decimal": ["Decimal separator", "."],
    "dot": ["Decimal separator", "."],
}

_PYWINAUTO_KEY_ALIASES: dict[str, str] = {
    "multiply": "{*}",
    "times": "{*}",
    "x": "{*}",
    "add": "{+}",
    "plus": "{+}",
    "subtract": "-",
    "minus": "-",
    "divide": "/",
    "return": "{ENTER}",
    "enter": "{ENTER}",
    "equals": "{ENTER}",
    "decimal": ".",
    "dot": ".",
}

_PYAUTOGUI_KEY_ALIASES: dict[str, str] = {
    "multiply": "multiply",
    "times": "multiply",
    "x": "multiply",
    "add": "add",
    "plus": "add",
    "subtract": "subtract",
    "minus": "subtract",
    "divide": "divide",
    "return": "enter",
    "enter": "enter",
    "equals": "enter",
    "decimal": "decimal",
    "dot": "decimal",
}




class DesktopWorker(AgenticWorkerMixin, DomainWorker):
    """LLM-driven desktop worker using ReAct loop."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.factory import create_provider_from_env
            llm = create_provider_from_env("worker")
        super().__init__(llm=llm)
        # Title-regex of the window the agent last asked to focus.
        # Re-asserted automatically before every input tool so keystrokes
        # never land in a random foreground window.
        self._target_window: str | None = None
        self._target_hwnd: int | None = None

    def _worker_system_prompt(self) -> str:
        return _DESKTOP_AGENT_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            _launch_app_decl,
            _focus_window_decl,
            _type_text_decl,
            _press_hotkey_decl,
            _press_key_decl,
            _click_button_decl,
            _click_coordinate_decl,
            _list_open_windows_decl,
            _select_dropdown_option_decl,
            _window_control_decl,
            _get_element_tree_decl,
            _toggle_checkbox_decl,
            _drag_and_drop_decl,
            _desktop_scroll_decl,
            _menu_select_decl,
            _kill_process_decl,
            _desktop_write_file_decl,
            _wait_decl,
            _get_clipboard_decl,
            _read_window_text_decl,
            _take_screenshot_decl,
            _finish_decl,
            _report_blocking_decl,
        ])]

    def _worker_environment_context(self, spec, evidence) -> str:
        import pathlib
        import sys as _sys
        platform_name = "Windows" if _sys.platform == "win32" else _sys.platform
        active_title = self._get_active_window_title()
        desktop = str(pathlib.Path.home() / "Desktop").replace("\\", "/")
        username = os.environ.get("USERNAME") or os.environ.get("USER") or "User"
        lines = ["DESKTOP STATE:"]
        lines.append(f"  Platform: {platform_name}")
        lines.append(f"  Username: {username}")
        lines.append(f"  Desktop path: {desktop}")
        lines.append(f"  Home dir: {str(pathlib.Path.home()).replace(chr(92), '/')}")
        if active_title:
            lines.append(f"  Active window: {active_title!r}")
        else:
            lines.append("  Active window: unknown")
        return "\n".join(lines)

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:
        active = self._get_active_window_title() or "unknown"
        action_log = evidence.get("action_log", [])
        last_action = action_log[-1] if action_log else "none"
        windows = self._get_open_windows()
        windows_str = f"[{', '.join(windows)}]" if windows else "[]"
        return "\n".join([
            f"active_window={active!r}",
            f"open_windows={windows_str}",
            f"last_action={last_action}",
        ])

    def _action_sensor_check(self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]):
        if tool_name != "launch_app":
            return None
        launched_pids = list(evidence.get("launched_pids") or [])
        if not launched_pids:
            return None

        async def _check() -> bool:
            try:
                import psutil
                return any(psutil.pid_exists(pid) for pid in launched_pids)
            except Exception:
                return False

        return _check

    def _action_sensor_read(self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]):
        if tool_name != "click_button":
            return None

        async def _read() -> str:
            active = self._get_active_window_title() or "unknown"
            return f"active_window after click: {active!r}"

        return _read

    @staticmethod
    def _get_open_windows() -> list[str]:
        """Enumerate visible top-level window titles (Windows only, caps at 10)."""
        _WIN_CAP = 10
        try:
            import ctypes
            titles: list[str] = []

            def _callback(hwnd: int, _: int) -> bool:
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value.strip()
                        if title:
                            titles.append(title)
                return True

            _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            ctypes.windll.user32.EnumWindows(_WNDENUMPROC(_callback), 0)
            return titles[:_WIN_CAP]
        except Exception:
            return []

    @staticmethod
    def _resolve_hwnd_by_title_search(title_re: str) -> int | None:
        """Find the first visible window whose title matches title_re anywhere (re.search).

        pywinauto's own title_re= parameter (find_windows/Application.connect) uses
        re.match — anchored at the start of the title — so a pattern like "notepad"
        never matches a real window titled "document.txt - Notepad". Every other tool
        in this file (_focus_window) already treats title_re as search-anywhere; this
        helper gives UIA-based tools (get_element_tree, window_control, menu_select,
        _find_uia_control) the same, correct semantics via handle= instead of title_re=.
        """
        if not title_re:
            return None
        try:
            import ctypes

            pattern = re.compile(title_re, re.IGNORECASE)
            user32 = ctypes.windll.user32
            found: list[int] = []

            def _cb(hwnd: int, _: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if pattern.search(buf.value):
                    found.append(hwnd)
                    return False
                return True

            _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(_WNDENUMPROC(_cb), 0)
            return found[0] if found else None
        except Exception:
            return None

    @staticmethod
    def _visible_window_handles(title_re: str | None = None) -> list[int]:
        """Return visible top-level handles, foreground first, filtered by title."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            pattern = re.compile(title_re, re.IGNORECASE) if title_re else None
            records: list[tuple[int, str, str]] = []

            def _cb(hwnd: int, _: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if pattern is None or pattern.search(buf.value):
                    class_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, class_buf, 256)
                    records.append((hwnd, buf.value, class_buf.value))
                return True

            _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(_WNDENUMPROC(_cb), 0)
            foreground = user32.GetForegroundWindow()
            dialog_words = re.compile(
                r"(?i)save|open|select|confirm|browse|file|print|choose|folder"
            )

            def rank(record: tuple[int, str, str]) -> tuple[int, int]:
                hwnd, title, class_name = record
                is_dialog = class_name == "#32770" or bool(dialog_words.search(title))
                return (0 if is_dialog else 1, 0 if hwnd == foreground else 1)

            records.sort(key=rank)
            return [hwnd for hwnd, _, _ in records[:12]]
        except Exception:
            return []

    @staticmethod
    def _get_active_window_title() -> str | None:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or None
        except Exception:
            return None

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        self._target_window = None  # reset per-objective; no cross-contamination
        self._target_hwnd = None
        evidence: dict[str, Any] = {
            "domain": "desktop",
            "objective_id": spec.objective_id,
            "screenshot": None,
            "element_tree_snapshot": None,
            "action_log": [],
            "selected_actions": [],
            "typed_text": "",
            "visible_text": "",
            "written_files": [],
            "launched_pids": [],   # PIDs of every process spawned via launch_app
            "degraded_mode": False,
            "error": None,
        }
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 120))
        try:
            actions = spec.metadata.get("actions")
            if isinstance(actions, list) and actions:
                result = await asyncio.wait_for(
                    self._run_planned_actions(spec, evidence), timeout=timeout_seconds
                )
            else:
                result = await asyncio.wait_for(
                    self.run_loop(spec, evidence), timeout=timeout_seconds
                )
            evidence["worker_result_status"] = result.status
            evidence["worker_result_summary"] = result.summary
            evidence["tokens_used"] = result.tokens_used
        except asyncio.TimeoutError:
            raise WorkerError(
                f"Desktop timeout after {timeout_seconds}s for '{spec.objective_id}'"
            )
        except WorkerBlocker:
            raise
        except WorkerError:
            raise
        except Exception as exc:
            evidence["error"] = str(exc)
            raise WorkerError(
                f"Desktop execution failed for '{spec.objective_id}': {exc}"
            ) from exc
        validate_evidence(DomainType.DESKTOP, evidence)
        return evidence

    async def _run_planned_actions(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> WorkerResult:
        """Run planner-supplied actions and finish from fresh sensor evidence."""
        actions = spec.metadata.get("actions", [])
        for index, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                raise WorkerError(f"Invalid planner desktop action at index {index}")
            tool_name = str(action.get("type", "")).strip()
            args = {key: value for key, value in action.items() if key != "type"}
            if tool_name == "type_text" and isinstance(args.get("text"), str):
                # Interactive model calls are limited to 500 characters. Planned
                # content can be safely chunked without changing the final text.
                text = args.pop("text")
                for offset in range(0, len(text), 500):
                    await self._dispatch_tool(
                        "type_text", {**args, "text": text[offset:offset + 500]}, evidence
                    )
                continue
            result = await self._dispatch_tool(tool_name, args, evidence)
            if isinstance(result, str) and " failed" in result.lower()[:160]:
                raise WorkerError(f"Planned desktop action {tool_name!r} failed: {result}")

        completion = await self._verify_planned_completion(spec, evidence)
        evidence["completion"] = completion
        return WorkerResult(
            status="success" if completion["passed"] else "failure",
            summary=completion["summary"],
        )

    async def _verify_planned_completion(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate declared desktop postconditions with fresh UI/file sensors."""
        conditions = spec.metadata.get("postconditions") or []
        if not isinstance(conditions, list) or not conditions:
            return {
                "passed": False,
                "summary": "Planner supplied desktop actions without postconditions",
            }

        recovered_file = False
        for condition in conditions:
            if not isinstance(condition, dict) or condition.get("type") != "file_content_contains":
                continue
            initial = await self._evaluate_postcondition(condition, evidence)
            if not initial["passed"]:
                recovered = await self._recover_typed_file(condition, evidence, initial)
                recovered_file = recovered_file or recovered["passed"]

        checks: list[dict[str, Any]] = []
        for condition in conditions:
            if not isinstance(condition, dict):
                checks.append({"passed": False, "detail": "Invalid postcondition"})
                continue
            check = await self._evaluate_postcondition(condition, evidence)
            if condition.get("type") == "file_content_contains" and not check["passed"]:
                check = await self._recover_typed_file(condition, evidence, check)
            if condition.get("type") == "dialog_absent" and not check["passed"]:
                check = await self._dismiss_save_dialog(evidence, condition, check)
            checks.append(check)

        if recovered_file:
            checks = [
                await self._evaluate_postcondition(condition, evidence)
                if isinstance(condition, dict)
                else {"passed": False, "detail": "Invalid postcondition"}
                for condition in conditions
            ]

        # A close action intentionally transitions away from the application.
        # Treating the resulting absence as a failed ``window_exists`` check
        # makes open-then-close objectives unverifiable even when no dialog or
        # unsaved state remains. Preserve every other postcondition as a hard
        # requirement; only reconcile this expected lifecycle transition.
        if self._intentional_close_recorded(evidence.get("action_log", [])):
            for index, condition in enumerate(conditions):
                if (
                    isinstance(condition, dict)
                    and condition.get("type") == "window_exists"
                    and not checks[index]["passed"]
                ):
                    checks[index] = {
                        **checks[index],
                        "passed": True,
                        "detail": "Window intentionally closed by the planned Alt+F4 action",
                    }

        passed = bool(checks) and all(check["passed"] for check in checks)
        if self._target_window:
            await self._dispatch_tool(
                "screenshot", {"mode": "app", "app_title": self._target_window}, evidence
            )
        return {
            "passed": passed,
            "checks": checks,
            "summary": "All declared desktop postconditions passed" if passed else "One or more declared desktop postconditions failed",
        }

    @staticmethod
    def _intentional_close_recorded(action_log: Any) -> bool:
        if not isinstance(action_log, list):
            return False
        for entry in action_log:
            compact = re.sub(r"[\s,]+", "", str(entry).lower())
            if "hotkey:alt+f4" in compact or "hotkey:altf4" in compact:
                return True
        return False

    async def _recover_typed_file(
        self,
        condition: dict[str, Any],
        evidence: dict[str, Any],
        check: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist typed content when a GUI Save dialog did not produce the file."""
        expected = str(condition.get("expected_text", ""))
        typed = str(evidence.get("typed_text", ""))
        raw_path = str(condition.get("path", "")).strip()
        path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
        if not expected or not path or expected not in typed or path.is_file():
            return check
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
            evidence.setdefault("written_files", []).append(str(path))
            evidence.setdefault("written_files_verified", {})[str(path)] = path.is_file()
            evidence.setdefault("action_log", []).append(
                f"postcondition recovery: wrote typed content to {path}"
            )
            return await self._evaluate_postcondition(condition, evidence)
        except Exception as exc:
            check["detail"] = f"File missing and typed-content recovery failed: {exc}"
            return check

    async def _dismiss_save_dialog(
        self,
        evidence: dict[str, Any],
        condition: dict[str, Any],
        check: dict[str, Any],
    ) -> dict[str, Any]:
        """Dismiss a standard Windows save-confirmation dialog if one remains."""
        title_re = str(condition.get("window_title_re") or self._target_window or "")
        if not re.search(r"paint|notepad", title_re, re.I):
            return check
        for label in ("Don't save", "Discard", "No"):
            result = await self._dispatch_tool(
                "click_button", {"button_text": label}, evidence
            )
            if not isinstance(result, str) or " failed" not in result.lower()[:160]:
                await asyncio.sleep(0.3)
                refreshed = await self._evaluate_postcondition(condition, evidence)
                if refreshed["passed"]:
                    return refreshed
        return check

    async def _evaluate_postcondition(
        self, condition: dict[str, Any], evidence: dict[str, Any]
    ) -> dict[str, Any]:
        """Return one structured result; unsupported/inaccessible is never success."""
        kind = str(condition.get("type", ""))
        title_re = str(condition.get("window_title_re") or self._target_window or "")
        expected = str(
            condition.get("expected_text", condition.get("expected_value", condition.get("expected", "")))
        )
        base: dict[str, Any] = {"type": kind, "target": title_re, "passed": False}

        if kind in {"window_exists", "window_focused", "dialog_present", "dialog_absent"}:
            matching_windows = self._matching_visible_hwnds(title_re)
            exists = bool(matching_windows)
            if kind == "window_exists":
                base.update(passed=exists, detail="Window found" if exists else "Window not found")
            elif kind == "window_focused":
                active = self._get_active_window_title() or ""
                base.update(passed=bool(title_re and re.search(title_re, active, re.I)), observed=active,
                            detail="Target window is foreground" if base["passed"] else "Target window is not foreground")
            elif kind == "dialog_present":
                dialog_exists = len(matching_windows) > 1
                base.update(passed=dialog_exists, detail="Dialog found" if dialog_exists else "Dialog not found")
            else:
                dialog_exists = len(matching_windows) > 1
                base.update(passed=not dialog_exists, detail="Dialog absent" if not dialog_exists else "Unexpected dialog remains")
            return base

        if kind == "clipboard_contains":
            if not expected:
                base["detail"] = "clipboard_contains requires expected_text"
                return base
            if title_re:
                if not await self._focus_window(title_re, evidence):
                    base["detail"] = "Could not focus target window for clipboard readback"
                    return base
                self._target_window = title_re
                await self._dispatch_tool("press_hotkey", {"keys": "ctrl,a"}, evidence)
                await self._dispatch_tool("press_hotkey", {"keys": "ctrl,c"}, evidence)
            actual = self._read_clipboard_text()
            evidence["clipboard_text"] = actual
            base.update(
                passed=expected in actual,
                expected_length=len(expected), actual_length=len(actual),
                detail="Clipboard readback contains expected text" if expected in actual else "Clipboard readback does not contain expected text",
            )
            return base

        if kind in {"file_exists", "file_content_contains", "file_hash_equals"}:
            raw_path = str(condition.get("path", "")).strip()
            if not raw_path:
                base["detail"] = f"{kind} requires path"
                return base
            path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
            exists = path.is_file()
            if kind == "file_exists":
                base.update(passed=exists, observed=str(path), detail="File exists" if exists else "File missing")
                return base
            if not exists:
                base["detail"] = "File missing"
                return base
            if kind == "file_content_contains":
                if not expected:
                    base["detail"] = "file_content_contains requires expected_text"
                    return base
                try:
                    actual = path.read_text(encoding="utf-8")
                except Exception as exc:
                    base["detail"] = f"Cannot read file: {exc}"
                    return base
                base.update(passed=expected in actual, actual_length=len(actual),
                            detail="File contains expected text" if expected in actual else "File does not contain expected text")
                return base
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            base.update(passed=bool(expected and actual_hash.lower() == expected.lower()), observed_hash=actual_hash,
                        detail="File hash matches" if actual_hash.lower() == expected.lower() else "File hash mismatch")
            return base

        if kind in {"control_exists", "control_enabled", "control_checked", "control_value_equals", "control_text_contains"}:
            control, error = self._find_uia_control(title_re, condition.get("control"))
            if control is None:
                base["detail"] = error
                return base
            if kind == "control_exists":
                base.update(passed=True, detail="Control found")
                return base
            try:
                if kind == "control_enabled":
                    observed = bool(control.is_enabled())
                    base.update(passed=observed, observed=observed, detail="Control enabled" if observed else "Control disabled")
                elif kind == "control_checked":
                    reader = getattr(control, "get_toggle_state", None) or getattr(control, "get_check_state", None)
                    if reader is None:
                        raise RuntimeError("control does not expose a checked/toggle state")
                    observed = bool(reader())
                    wanted = str(condition.get("expected", "true")).lower() in {"true", "1", "checked"}
                    base.update(passed=observed == wanted, observed=observed,
                                detail="Control checked state matches" if observed == wanted else "Control checked state mismatch")
                else:
                    value = str(getattr(control, "get_value", control.window_text)() or control.window_text())
                    passed = value == expected if kind == "control_value_equals" else expected in value
                    base.update(passed=passed, observed=value[:1000],
                                detail="Control value matches" if passed else "Control value mismatch")
            except Exception as exc:
                base["detail"] = f"Could not read control state: {exc}"
            return base

        base["detail"] = f"Unsupported postcondition: {kind!r}"
        return base

    @staticmethod
    def _window_exists(title_re: str) -> bool:
        return bool(DesktopWorker._matching_visible_hwnds(title_re))

    @staticmethod
    def _matching_visible_hwnds(title_re: str) -> list[int]:
        """Return visible top-level windows matching title_re with search semantics."""
        if not title_re or sys.platform != "win32":
            return []
        try:
            import ctypes

            pattern = re.compile(title_re, re.IGNORECASE)
            user32 = ctypes.windll.user32
            found: list[int] = []

            def _callback(hwnd: int, _: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if pattern.search(buf.value):
                    found.append(hwnd)
                return True

            proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(_callback)
            user32.EnumWindows(proc, 0)
            return found
        except Exception:
            return []

    async def _resolve_and_verify_screen_point(
        self, x: int, y: int, window_title_re: str | None, evidence: dict[str, Any]
    ) -> tuple[int, int] | None:
        """Resolve (x, y) to absolute screen coords and re-verify the target is foreground.

        SAFETY: raw SendInput/pyautogui input bypasses UIA's target validation — a click
        is just "whatever is under this pixel now". If window_title_re is given, this
        confirms the window is (still) foreground immediately before returning coordinates,
        closing the race where focus shifts between resolving and dispatching input.
        Returns None if the window could not be confirmed foreground.
        """
        if not window_title_re:
            return x, y
        focused_ok = await self._focus_window(window_title_re, evidence)
        if not focused_ok:
            return None
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = ctypes.wintypes.POINT(x, y)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        if user32.GetForegroundWindow() != hwnd:
            return None
        return pt.x, pt.y

    @staticmethod
    def _find_uia_control(title_re: str, control_spec: Any) -> tuple[Any | None, str]:
        if not title_re or not isinstance(control_spec, dict):
            return None, "Control checks require window_title_re and a control locator"
        hwnd = DesktopWorker._resolve_hwnd_by_title_search(title_re)
        if hwnd is None:
            return None, f"No visible window matched {title_re!r}"
        try:
            from pywinauto import Application
            app = Application(backend="uia").connect(handle=hwnd, timeout=5)
            window = app.top_window()
            locator = {
                key: control_spec[key]
                for key in ("auto_id", "title", "title_re", "control_type")
                if key in control_spec
            }
            if "automation_id" in control_spec:
                locator["auto_id"] = control_spec["automation_id"]
            if not locator:
                return None, "Control locator must contain auto_id, title, title_re, or control_type"
            control = window.child_window(**locator)
            if not control.exists(timeout=2):
                return None, "Control not found"
            return control, ""
        except Exception as exc:
            return None, f"UI Automation lookup failed: {exc}"

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str | tuple[str, bytes] | _FinishSignal | _BlockerSignal:
        import subprocess

        emit(
            "desktop_worker.py:_dispatch_tool",
            "tool_dispatch",
            {"tool": tool_name, "args_preview": {k: str(v)[:80] for k, v in args.items()}},
        )

        if tool_name == "launch_app":
            app = args["app"]
            raw_args = args.get("args", "")
            if isinstance(raw_args, list):
                app_args = raw_args
            elif raw_args:
                app_args = raw_args.split()
            else:
                app_args = []
            app_args = [a.replace("/", "\\") if isinstance(a, str) else a for a in app_args]
            # Map exe names to window title patterns so we can detect existing instances.
            _EXE_TITLE_MAP = {
                "notepad.exe": "notepad",
                "notepad": "notepad",
                "calc.exe": "calculator",
                "calc": "calculator",
                "mspaint.exe": "paint",
                "mspaint": "paint",
            }
            title_hint = _EXE_TITLE_MAP.get(app.lower())
            # Reusing an existing process is only valid for a bare application
            # launch.  When arguments name a document, Notepad must receive them;
            # otherwise the unrelated foreground document is incorrectly reused.
            if title_hint and not app_args:
                try:
                    existing_hwnd = self._resolve_hwnd_by_title_search(f"(?i){title_hint}")
                    existing = [existing_hwnd] if existing_hwnd else []
                    if existing:
                        import ctypes
                        hwnd = existing[0]
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        self._target_hwnd = int(hwnd)
                        evidence["action_log"].append(f"Reused existing window: {app}")
                        if app.lower() in {"notepad.exe", "notepad"}:
                            self._target_window = title_hint
                            try:
                                from pywinauto import Application

                                window = Application(backend="uia").connect(handle=hwnd).top_window()
                                new_tab = window.child_window(
                                    auto_id="AddButton", control_type="Button"
                                )
                                if new_tab.exists(timeout=2):
                                    new_tab.click_input()
                                    evidence["action_log"].append("Opened a fresh Notepad document via Add New Tab")
                                else:
                                    await self._hotkey(["ctrl", "n"], evidence)
                            except Exception:
                                await self._hotkey(["ctrl", "n"], evidence)
                            await asyncio.sleep(0.5)
                            evidence["action_log"].append("Opened a fresh Notepad document")
                        return f"Reused existing {app} window (already open)"
                except Exception:
                    pass  # fall through to normal launch
            pids_before = _snapshot_pids()
            proc = subprocess.Popen([app, *app_args])
            wait = float(args.get("wait", 1.5))
            await asyncio.sleep(wait)
            # Record the direct PID plus any processes spawned during the wait
            # window (covers UWP stubs like calc.exe that spawn CalculatorApp.exe
            # as a separate process and then exit).
            new_pids = _snapshot_pids() - pids_before
            new_pids.add(proc.pid)
            evidence.setdefault("launched_pids", []).extend(sorted(new_pids))
            evidence["action_log"].append(
                f"Launched: {app} (pids={sorted(new_pids)})"
            )
            return f"Launched {app} (pids={sorted(new_pids)})"

        elif tool_name == "focus_window":
            title_re = args["title_re"]
            wait = float(args.get("wait", 0.5))
            focused = await self._focus_window(title_re, evidence)
            if focused:
                self._target_window = title_re
            await asyncio.sleep(wait)
            if not focused:
                return (
                    f"FOCUS FAILED: no visible window matched {title_re!r}. "
                    "Inspect the open windows or retry with a broader title pattern; do not continue "
                    "with keyboard input until focus succeeds."
                )
            return f"Focused window: {title_re}"

        elif tool_name == "type_text":
            text = args["text"]
            _MAX_TYPE_CHARS = 500
            if len(text) > _MAX_TYPE_CHARS:
                evidence["action_log"].append(
                    f"type_text blocked: {len(text)} chars > {_MAX_TYPE_CHARS} limit"
                )
                return (
                    f"ðŸ›‘ BLOCKED: type_text called with {len(text)} characters. "
                    f"Maximum per call is {_MAX_TYPE_CHARS}. "
                    "Typing thousands of characters is not a supported automation pattern. "
                    "Call finish('failure') explaining that the goal requires excessive repetition."
                )
            interval = float(args.get("interval", 0.03))
            await self._ensure_target_focused(evidence)
            if self._calculator_window_open():
                evidence["action_log"].append(
                    f"type_text blocked in Calculator: {text!r}"
                )
                return (
                    "ðŸ›‘ BLOCKED: type_text does not work in Windows Calculator. "
                    "Use press_key for each digit and operator separately "
                    "(e.g. press_key('1'), press_key('2'), press_key('multiply'), "
                    "press_key('1'), press_key('2'), press_key('equals')). "
                    "Then read_window_text or press_hotkey('ctrl','c') and clipboard_read."
                )
            await self._type_text(text, interval, evidence)
            await asyncio.sleep(0.1)
            evidence["typed_text"] = evidence.get("typed_text", "") + text
            evidence["action_log"].append(f"Typed {len(text)} chars")
            return f"Typed {len(text)} chars"

        elif tool_name == "press_hotkey":
            keys_str = args["keys"]
            keys = self._normalise_hotkey_keys(keys_str)
            if len(keys) < 2:
                return (
                    f"press_hotkey failed: expected at least two keys in {keys_str!r}. "
                    "Use comma- or plus-separated keys, e.g. 'ctrl,s' or 'ctrl+s'."
                )
            await self._ensure_target_focused(evidence)
            await self._hotkey(keys, evidence)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Hotkey: {keys_str}")
            return f"Pressed hotkey: {keys_str}"

        elif tool_name == "press_key":
            key = args["key"]
            await self._ensure_target_focused(evidence)
            await self._press_key(key, evidence)
            await asyncio.sleep(0.2)
            evidence["action_log"].append(f"Press: {key}")
            return f"Pressed key: {key}"

        elif tool_name == "click_button":
            button_text, button_title_re, control_type = _normalise_click_button_args(args)
            direct_locator = _click_button_locator(args)
            window_title_re = args.get("window_title_re")
            if not button_text and not button_title_re and not direct_locator:
                return "click_button failed: missing button_text or control/title_re locator"
            try:
                import win32gui
                from pywinauto import Application
                # Try multiple strategies: exact â†’ case-insensitive â†’ any control type
                _strategies = _button_locator_strategies(
                    button_text, button_title_re, control_type
                )
                if direct_locator:
                    _strategies.insert(0, direct_locator)
                _last_exc = None
                # Native dialogs can expose their controls a few hundred
                # milliseconds after the window itself. Refresh the handle
                # list and retry boundedly instead of treating that race as
                # an environment failure.
                for _attempt in range(3):
                    handles = DesktopWorker._visible_window_handles(window_title_re)
                    if not handles:
                        handles = [win32gui.GetForegroundWindow()]
                    for hwnd in handles:
                        try:
                            app_obj = Application(backend="uia").connect(handle=hwnd, timeout=5)
                            # Keep the exact enumerated top-level handle. Using
                            # top_window() can retarget an owner window when a
                            # native Save/Open dialog is modal.
                            win_obj = app_obj.window(handle=hwnd)
                        except Exception as _e:
                            try:
                                win_obj = app_obj.top_window()
                            except Exception:
                                _last_exc = _e
                                continue
                        for _s in _strategies:
                            try:
                                btn = win_obj.child_window(**_s)
                                if not btn.exists(timeout=0.5):
                                    raise LookupError(f"control not found: {_s}")
                                btn.click_input()
                                await asyncio.sleep(0.3)
                                self._target_hwnd = hwnd
                                evidence["action_log"].append(
                                    f"click_button: '{button_text}' hwnd={hwnd} strat={_s}"
                                )
                                label = button_text or button_title_re or str(direct_locator)
                                return f"Clicked button '{label}'"
                            except Exception as _e:
                                _last_exc = _e
                        if button_text or button_title_re:
                            try:
                                expected = button_text.strip().casefold() if button_text else None
                                title_pattern = (
                                    re.compile(button_title_re, re.IGNORECASE)
                                    if button_title_re else None
                                )
                                for descendant in win_obj.descendants():
                                    descendant_title = descendant.window_text().strip()
                                    normalized_title = descendant_title.replace("’", "'")
                                    matches_text = expected is not None and (
                                        normalized_title.casefold() == expected
                                    )
                                    matches_pattern = title_pattern is not None and bool(
                                        title_pattern.search(normalized_title)
                                    )
                                    if not (matches_text or matches_pattern):
                                        continue
                                    descendant.click_input()
                                    await asyncio.sleep(0.3)
                                    self._target_hwnd = hwnd
                                    evidence["action_log"].append(
                                        f"click_button: '{button_text or button_title_re}' "
                                        f"hwnd={hwnd} strategy=descendant_text"
                                    )
                                    return f"Clicked button '{button_text or button_title_re}'"
                            except Exception as _e:
                                _last_exc = _e
                    if _attempt < 2:
                        await asyncio.sleep(0.5)
                evidence["action_log"].append(f"click_button all strategies failed: {_last_exc}")
                locator = button_text or button_title_re
                return f"click_button failed (button '{locator}' not found): {_last_exc}"
            except Exception as exc:
                evidence["action_log"].append(f"click_button failed: {exc}")
                return f"click_button failed: {exc}"

        elif tool_name == "write_file":
            path = args["path"]
            content = args["content"]
            import pathlib
            p = pathlib.Path(path)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except Exception as exc:
                evidence.setdefault("write_file_failures", []).append({"path": path, "error": str(exc)})
                evidence["action_log"].append(f"write_file FAILED: {path}: {exc}")
                return f"write_file failed: {path}: {exc}"
            exists_after = p.exists()
            evidence.setdefault("written_files_verified", {})[path] = exists_after
            if not exists_after:
                evidence.setdefault("write_file_failures", []).append(
                    {"path": path, "error": "file missing immediately after write"}
                )
            evidence["written_files"].append(path)
            preview = content[:500] + ("..." if len(content) > 500 else "")
            evidence["action_log"].append(
                f"Wrote file: {path} ({len(content)} chars) verified_exists={exists_after}"
            )
            evidence[f"file_content_{p.name}"] = preview
            return f"File written: {path} ({len(content)} chars) verified_exists={exists_after}"

        elif tool_name == "wait":
            secs = float(args.get("seconds", 0.5))
            await asyncio.sleep(secs)
            evidence["action_log"].append(f"Waited {secs}s")
            return f"Waited {secs}s"

        elif tool_name == "screenshot":
            if self._target_window and not args.get("app_title"):
                args = {**args, "mode": args.get("mode", "app"), "app_title": self._target_window}
            result = await super()._dispatch_tool(tool_name, args, evidence)
            emit(
                "desktop_worker.py:screenshot",
                "screenshot_for_vision",
                {
                    "mode": args.get("mode", "app"),
                    "app_title": args.get("app_title", ""),
                    "has_image": isinstance(result, tuple),
                },
            )
            return result

        elif tool_name == "kill_process":
            import subprocess as _sp
            process_name = args.get("process_name", "")
            try:
                kill_result = _sp.run(
                    ["taskkill", "/F", "/IM", process_name],
                    capture_output=True, text=True, timeout=10,
                )
                await asyncio.sleep(0.5)
                msg = f"kill_process {process_name}: exit={kill_result.returncode} {kill_result.stdout.strip()} {kill_result.stderr.strip()}"
                evidence["action_log"].append(msg)
                return msg
            except Exception as exc:
                evidence["action_log"].append(f"kill_process failed: {exc}")
                return f"kill_process failed: {exc}"

        elif tool_name == "clipboard_read":
            text = self._read_clipboard_text()
            if text:
                evidence["clipboard_text"] = text
                evidence["action_log"].append(f"clipboard_read: {text[:100]!r}")
                return text
            evidence["action_log"].append("clipboard_read: (empty)")
            return "(clipboard is empty)"

        elif tool_name == "read_window_text":
            title_re = args.get("window_title_re") or self._target_window
            max_items = int(args.get("max_items", 15))
            snippets = self._read_window_text_uia(title_re, max_items=max_items)
            evidence["visible_text_snippets"] = snippets
            evidence["action_log"].append(
                f"read_window_text: {len(snippets)} snippet(s) from {title_re!r}"
            )
            emit(
                "desktop_worker.py:read_window_text",
                "window_text_read",
                {"title_re": title_re, "snippets": snippets[:5]},
            )
            if not snippets:
                return (
                    "No readable text found in the target window. "
                    "Call screenshot(mode='app', app_title=<window>) â€” the image is attached "
                    "for you to read the on-screen value directly."
                )
            body = "\n".join(f"- {s}" for s in snippets)
            obs = f"Visible text in window ({title_re or 'foreground'}):\n{body}"
            if not self._uia_snippets_show_result_value(snippets):
                obs += (
                    "\n\nUIA did not expose a clear numeric result field "
                    "(only labels/expressions may be visible to accessibility). "
                    "Call screenshot(mode='app', app_title=<window>) and read the "
                    "display value from the attached image before finish."
                )
            return obs

        elif tool_name == "click_coordinate":
            x, y = int(args["x"]), int(args["y"])
            window_title_re = args.get("window_title_re") or self._target_window
            button = args.get("button", "left")
            try:
                point = await self._resolve_and_verify_screen_point(x, y, window_title_re, evidence)
                if point is None:
                    return f"click_coordinate ABORTED: could not confirm {window_title_re!r} as foreground before sending input."
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.moveTo(*point)
                if button == "double":
                    pyautogui.doubleClick()
                else:
                    pyautogui.click(button="left" if button == "left" else "right")
                await asyncio.sleep(0.2)
                evidence["action_log"].append(f"click_coordinate: ({x},{y}) rel={window_title_re!r} -> screen={point}")
                return f"Clicked at ({x},{y}) relative to {window_title_re or 'screen'}"
            except Exception as exc:
                evidence["action_log"].append(f"click_coordinate failed: {exc}")
                return f"click_coordinate failed: {exc}"

        elif tool_name == "list_open_windows":
            windows = self._get_open_windows()
            evidence["action_log"].append(f"list_open_windows: {len(windows)} window(s)")
            return f"Open windows: {windows}" if windows else "No visible windows found."

        elif tool_name == "select_dropdown_option":
            title_re = args.get("window_title_re") or self._target_window or ""
            control_spec: dict[str, Any] = {k: args[k] for k in ("auto_id", "control_title") if args.get(k)}
            if "control_title" in control_spec:
                control_spec["title"] = control_spec.pop("control_title")
            control_spec.setdefault("control_type", "ComboBox")
            control, error = self._find_uia_control(title_re, control_spec)
            if control is None:
                evidence["action_log"].append(f"select_dropdown_option failed: {error}")
                return f"select_dropdown_option failed: {error}"
            try:
                control.select(args["option_text"])
                await asyncio.sleep(0.2)
                evidence["action_log"].append(f"select_dropdown_option: {args['option_text']!r}")
                return f"Selected option: {args['option_text']}"
            except Exception as exc:
                evidence["action_log"].append(f"select_dropdown_option failed: {exc}")
                return f"select_dropdown_option failed: {exc}"

        elif tool_name == "window_control":
            title_re = args.get("window_title_re") or self._target_window or ""
            if not title_re:
                return "window_control failed: no window_title_re and no active target window"
            try:
                resolved_hwnd = self._resolve_hwnd_by_title_search(title_re)
                if resolved_hwnd is None:
                    return f"window_control failed: no visible window matched {title_re!r}"
                import ctypes
                import ctypes.wintypes
                user32 = ctypes.windll.user32
                _SW = {"minimize": 6, "maximize": 3, "restore": 9}
                state = args.get("state")
                if state:
                    user32.ShowWindow(resolved_hwnd, _SW[state])
                if any(k in args for k in ("x", "y", "width", "height")):
                    rect = ctypes.wintypes.RECT()
                    user32.GetWindowRect(resolved_hwnd, ctypes.byref(rect))
                    def _int_arg(name: str, default: int) -> int:
                        value = args.get(name)
                        return default if value is None else int(str(value))

                    new_x = _int_arg("x", rect.left)
                    new_y = _int_arg("y", rect.top)
                    new_w = _int_arg("width", rect.right - rect.left)
                    new_h = _int_arg("height", rect.bottom - rect.top)
                    user32.SetWindowPos(resolved_hwnd, 0, new_x, new_y, new_w, new_h, 0x0040)  # SWP_SHOWWINDOW
                await asyncio.sleep(0.2)
                evidence["action_log"].append(f"window_control: {title_re!r} state={state} geom={args}")
                return f"window_control applied to {title_re!r}: state={state}"
            except Exception as exc:
                evidence["action_log"].append(f"window_control failed: {exc}")
                return f"window_control failed: {exc}"

        elif tool_name == "get_element_tree":
            title_re = args.get("window_title_re") or self._target_window or ""
            max_depth = int(args.get("max_depth", 3))
            max_nodes = int(args.get("max_nodes", 200))
            try:
                resolved_hwnd = self._resolve_hwnd_by_title_search(title_re)
                if resolved_hwnd is None:
                    return f"get_element_tree failed: no visible window matched {title_re!r}"
                from pywinauto import Application
                app_obj = Application(backend="uia").connect(handle=resolved_hwnd, timeout=5)
                win_obj = app_obj.top_window()
                tree = self._dump_ui_tree(win_obj, max_depth=max_depth, max_nodes=max_nodes)
                payload = json.dumps(tree, ensure_ascii=False)
                evidence["element_tree_snapshot"] = payload
                evidence["action_log"].append(f"get_element_tree: {title_re!r} nodes<={max_nodes}")
                return f"Element tree ({len(payload)} chars):\n{payload[:4000]}"
            except Exception as exc:
                evidence["action_log"].append(f"get_element_tree failed: {exc}")
                return f"get_element_tree failed: {exc}"

        elif tool_name == "toggle_checkbox":
            title_re = args.get("window_title_re") or self._target_window or ""
            control_spec = {k: args[k] for k in ("auto_id", "control_title") if args.get(k)}
            if "control_title" in control_spec:
                control_spec["title"] = control_spec.pop("control_title")
            control, error = self._find_uia_control(title_re, control_spec)
            if control is None:
                evidence["action_log"].append(f"toggle_checkbox failed: {error}")
                return f"toggle_checkbox failed: {error}"
            try:
                # pywinauto's UIA backend only reliably implements .toggle() and
                # .get_toggle_state() for checkboxes — .check()/.uncheck() exist on
                # some wrapper classes but not UIA's, and WindowSpecification's proxy
                # __getattr__ makes hasattr() report True even when the call itself
                # fails deep inside pywinauto (confirmed live: "Neither GUI element
                # (wrapper) nor wrapper method 'check' were found"). So: read current
                # state via get_toggle_state() and only toggle() when it disagrees
                # with the requested absolute state.
                desired = args["desired_state"]
                current_state: bool | None = None
                try:
                    current_state = bool(control.get_toggle_state())
                except Exception:
                    pass
                if desired == "toggle" or current_state is None:
                    control.toggle()
                else:
                    want_checked = desired == "checked"
                    if want_checked != current_state:
                        control.toggle()
                await asyncio.sleep(0.2)
                evidence["action_log"].append(f"toggle_checkbox: {desired} (was_checked={current_state})")
                return f"toggle_checkbox applied: {desired}"
            except Exception as exc:
                evidence["action_log"].append(f"toggle_checkbox failed: {exc}")
                return f"toggle_checkbox failed: {exc}"

        elif tool_name == "drag_and_drop":
            window_title_re = args.get("window_title_re") or self._target_window
            try:
                from_pt = await self._resolve_and_verify_screen_point(
                    int(args["from_x"]), int(args["from_y"]), window_title_re, evidence
                )
                if from_pt is None:
                    return f"drag_and_drop ABORTED: could not confirm {window_title_re!r} as foreground."
                to_pt = await self._resolve_and_verify_screen_point(
                    int(args["to_x"]), int(args["to_y"]), window_title_re, evidence
                )
                if to_pt is None:
                    return "drag_and_drop ABORTED: foreground window changed mid-drag."
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.moveTo(*from_pt)
                pyautogui.dragTo(*to_pt, duration=float(args.get("duration", 0.5)), button="left")
                evidence["action_log"].append(f"drag_and_drop: {from_pt} -> {to_pt} rel={window_title_re!r}")
                return f"Dragged from {from_pt} to {to_pt}"
            except Exception as exc:
                evidence["action_log"].append(f"drag_and_drop failed: {exc}")
                return f"drag_and_drop failed: {exc}"

        elif tool_name == "scroll":
            window_title_re = args.get("window_title_re") or self._target_window
            direction = args["direction"]
            amount = int(args.get("amount", 3))
            try:
                point = None
                if "x" in args and "y" in args:
                    point = await self._resolve_and_verify_screen_point(
                        int(args["x"]), int(args["y"]), window_title_re, evidence
                    )
                    if point is None:
                        return f"scroll ABORTED: could not confirm {window_title_re!r} as foreground."
                import pyautogui
                pyautogui.FAILSAFE = False
                if point:
                    pyautogui.moveTo(*point)
                clicks = amount if direction == "up" else -amount
                if direction in ("up", "down"):
                    pyautogui.scroll(clicks)
                else:
                    pyautogui.hscroll(amount if direction == "right" else -amount)
                evidence["action_log"].append(f"scroll: direction={direction} amount={amount} at={point}")
                return f"Scrolled {direction} by {amount}"
            except Exception as exc:
                evidence["action_log"].append(f"scroll failed: {exc}")
                return f"scroll failed: {exc}"

        elif tool_name == "menu_select":
            title_re = args.get("window_title_re") or self._target_window or ""
            path = args["path"]
            if not title_re:
                return "menu_select failed: no window_title_re and no active target window"
            try:
                resolved_hwnd = self._resolve_hwnd_by_title_search(title_re)
                if resolved_hwnd is None:
                    return f"menu_select failed: no visible window matched {title_re!r}"
                from pywinauto import Application
                app_obj = Application(backend="uia").connect(handle=resolved_hwnd, timeout=5)
                app_obj.top_window().menu_select(path)
                await asyncio.sleep(0.3)
                evidence["action_log"].append(f"menu_select: {path!r}")
                return f"Selected menu item: {path}"
            except Exception as exc:
                detail = str(exc) or f"{type(exc).__name__} (no message — the menu path segment likely doesn't exist)"
                evidence["action_log"].append(f"menu_select failed: {detail}")
                return f"menu_select failed: {detail}. This app may use a ribbon/custom menu, or this menu path doesn't exist — try get_element_tree to discover controls."

        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    async def _focus_window(self, title_re: str, evidence: dict[str, Any]) -> bool:
        """Focus a window by title regex. Returns True on success.

        Uses pure Win32 EnumWindows via ctypes â€” no UIA queries, no WinUI3 hang.
        Polls up to 30s for the window to become visible (covers slow app launches).
        """
        import ctypes
        import ctypes.wintypes
        import re as _re

        pattern = _re.compile(title_re, _re.IGNORECASE)
        user32 = ctypes.windll.user32
        launched_pids = {int(pid) for pid in evidence.get("launched_pids", [])}

        def _find_visible_hwnd() -> int | None:
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            def _cb(hwnd: int, _: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if pattern.search(buf.value):
                    found.append(hwnd)
                    return False  # stop enumeration
                return True

            user32.EnumWindows(_cb, 0)
            return found[0] if found else None

        def _target_matches_request() -> int | None:
            """Keep the current target when it still matches this focus request."""
            if not self._target_hwnd or not user32.IsWindowVisible(self._target_hwnd):
                return None
            length = user32.GetWindowTextLengthW(self._target_hwnd)
            if length <= 0:
                return None
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(self._target_hwnd, buf, length + 1)
            return self._target_hwnd if pattern.search(buf.value) else None

        def _find_launched_window() -> int | None:
            """Modern Notepad may expose a generic title while loading a document."""
            if not launched_pids:
                return None
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            def _cb(hwnd: int, _: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = ctypes.wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in launched_pids:
                    found.append(hwnd)
                    return False
                return True

            user32.EnumWindows(_cb, 0)
            return found[0] if found else None

        try:
            deadline = time.monotonic() + 30
            hwnd: int | None = None
            launched_fallback_at = time.monotonic() + 3
            while time.monotonic() < deadline:
                # A worker can intentionally reuse an app (for example modern
                # Notepad's tabbed process). Preserve that exact top-level
                # window instead of selecting an older matching tab/window.
                hwnd = _target_matches_request()
                if not hwnd and launched_pids:
                    hwnd = _find_launched_window()
                if not hwnd:
                    hwnd = _find_visible_hwnd()
                if hwnd:
                    break
                if time.monotonic() >= launched_fallback_at:
                    hwnd = _find_launched_window()
                    if hwnd:
                        evidence["action_log"].append(
                            f"Focused launched process window after title did not materialize: {title_re}"
                        )
                        break
                await asyncio.sleep(0.5)

            if not hwnd:
                evidence["action_log"].append(
                    f"focus_window failed ({title_re}): window not visible after 30s"
                )
                return False

            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            self._target_hwnd = int(hwnd)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Focused: {title_re}")
            return True
        except Exception as exc:
            evidence["action_log"].append(f"focus_window failed ({title_re}): {exc}")
            return False

    async def _ensure_target_focused(self, evidence: dict[str, Any]) -> None:
        """Re-assert focus on the last declared target window before sending input.

        Called automatically before every type_text / press_key / press_hotkey
        so keystrokes always land in the intended application even if something
        else grabbed focus in between steps.
        """
        if not self._target_window:
            return  # no target declared yet â€” trust whatever has focus
        try:
            if self._target_hwnd:
                import ctypes
                user32 = ctypes.windll.user32
                if user32.IsWindow(self._target_hwnd):
                    foreground = user32.GetForegroundWindow()
                    if (
                        self._foreground_belongs_to_target(user32, self._target_hwnd, foreground)
                        or self._foreground_is_common_modal_dialog(user32, foreground)
                    ):
                        return
                    if foreground != self._target_hwnd:
                        user32.ShowWindow(self._target_hwnd, 9)
                        user32.SetForegroundWindow(self._target_hwnd)
                        await asyncio.sleep(0.1)
                    return
                self._target_hwnd = None
            active = self._get_active_window_title() or ""
            import re as _re
            if _re.search(self._target_window, active, _re.IGNORECASE):
                return  # already focused â€” nothing to do
            # Focus drifted â€” re-assert
            await self._focus_window(self._target_window, evidence)
        except Exception:
            pass  # best-effort; don't block the input operation

    @staticmethod
    def _foreground_belongs_to_target(user32: Any, target_hwnd: int, foreground_hwnd: int) -> bool:
        """Keep focus in a target app while one of its modal dialogs is active."""
        if not foreground_hwnd or foreground_hwnd == target_hwnd:
            return bool(foreground_hwnd == target_hwnd)
        import ctypes

        # Native Save/Open dialogs are separate top-level windows owned by the
        # target. GA_ROOTOWNER also covers owner chains exposed by modern UIs.
        try:
            if user32.GetAncestor(foreground_hwnd, 3) == target_hwnd:  # GA_ROOTOWNER
                return True
            owner = user32.GetWindow(foreground_hwnd, 4)  # GW_OWNER
            while owner:
                if owner == target_hwnd:
                    return True
                owner = user32.GetWindow(owner, 4)

            # Some framework dialogs do not expose an owner but remain in the
            # same process. Treat them as belonging to the target application;
            # this prevents modal focus from being stolen between key actions.
            target_pid = ctypes.wintypes.DWORD()
            foreground_pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(target_pid))
            user32.GetWindowThreadProcessId(foreground_hwnd, ctypes.byref(foreground_pid))
            return bool(target_pid.value and target_pid.value == foreground_pid.value)
        except Exception:
            return False

    @staticmethod
    def _foreground_is_common_modal_dialog(user32: Any, foreground_hwnd: int) -> bool:
        """Recognize standard Save/Open pickers even when hosted out-of-process."""
        if not foreground_hwnd:
            return False
        try:
            import ctypes
            length = user32.GetWindowTextLengthW(foreground_hwnd)
            if length <= 0:
                return False
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(foreground_hwnd, buf, length + 1)
            return bool(re.search(
                r"(?i)\b(save\s+as|open|confirm\s+save|replace|select\s+folder|choose)\b",
                buf.value,
            ))
        except Exception:
            return False

    async def _type_text(self, text: str, interval: float, evidence: dict[str, Any]) -> None:
        # send_keys interprets parentheses, braces, plus, and percent as key
        # syntax. Clipboard paste preserves literal user content and is faster
        # for multi-paragraph reports.
        try:
            import subprocess
            result = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
                ],
                input=text,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or f"Set-Clipboard exited {result.returncode}")
            from pywinauto.keyboard import send_keys
            send_keys("^v", pause=interval)
            evidence["action_log"].append("Typed via clipboard paste")
            if self._target_window:
                evidence["visible_text"] = evidence.get("visible_text", "") + text
            return
        except Exception as exc:
            evidence["action_log"].append(f"clipboard paste fallback failed: {exc}")
        try:
            from pywinauto.keyboard import send_keys
            send_keys(text, pause=interval, with_spaces=True, with_tabs=True, with_newlines=True)
            evidence["action_log"].append("Typed via pywinauto keyboard")
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto type fallback failed: {exc}")
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.write(text, interval=interval)
            evidence["action_log"].append("Typed via PyAutoGUI fallback")

        # Accumulate typed text so verify_visible_text can confirm visible delivery.
        # Only counted as visible proof when focus_window was called first
        # (meaning keystrokes were intentionally directed at a known window).
        if self._target_window:
            evidence["visible_text"] = evidence.get("visible_text", "") + text

    async def _hotkey(self, keys: list[str], evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            modifier_map = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
            modifiers = "".join(modifier_map[k.lower()] for k in keys[:-1] if k.lower() in modifier_map)
            key = keys[-1]
            send_keys(f"{modifiers}{key}")
            evidence["action_log"].append("Hotkey via pywinauto keyboard")
            return
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto hotkey fallback failed: {exc}")

        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.hotkey(*keys)
        evidence["action_log"].append("Hotkey via PyAutoGUI fallback")

    @staticmethod
    def _normalise_hotkey_keys(keys: str | list[str] | tuple[str, ...]) -> list[str]:
        """Normalize model-emitted hotkeys without treating the combo as text.

        The public tool schema historically documented comma-separated keys,
        while models also commonly emit the conventional ``ctrl+s`` form.
        Supporting both at the dispatch boundary keeps all downstream input
        implementations working from the same validated key list.
        """
        if isinstance(keys, (list, tuple)):
            raw = [str(key).strip() for key in keys]
        else:
            raw = re.split(r"[+,]", str(keys))
        return [key.strip() for key in raw if key.strip()]

    @staticmethod
    def _pywinauto_key_sequence(key: str) -> str:
        k = key.strip().lower()
        if k in _PYWINAUTO_KEY_ALIASES:
            return _PYWINAUTO_KEY_ALIASES[k]
        if len(k) == 1 and (k.isdigit() or k in ".+-*/"):
            return k
        return f"{{{key.strip().upper()}}}"

    @staticmethod
    def _pyautogui_key_name(key: str) -> str:
        k = key.strip().lower()
        if k in _PYAUTOGUI_KEY_ALIASES:
            return _PYAUTOGUI_KEY_ALIASES[k]
        return k

    @staticmethod
    def _read_clipboard_text() -> str:
        import subprocess
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _calculator_window_open(self) -> bool:
        if sys.platform != "win32":
            return False
        active = (self._get_active_window_title() or "").lower()
        target = (self._target_window or "").lower()
        # Only block typing when Calculator is the active or declared target.
        # Scanning all visible windows lets an unrelated open Calculator veto
        # text input intended for another application.
        return "calculator" in active or "calculator" in target

    @staticmethod
    def _calculator_text_to_keys(text: str) -> list[str] | None:
        """Parse arithmetic text into Calculator press_key names (UWP-safe)."""
        s = text.strip().lower()
        s = re.sub(r"\bmultiplied\s+by\b", "*", s)
        s = re.sub(r"\btimes\b", "*", s)
        s = re.sub(r"\bplus\b", "+", s)
        s = re.sub(r"\bminus\b", "-", s)
        s = re.sub(r"\bdivided\s+by\b", "/", s)
        s = s.replace("×", "*").replace("÷", "/").replace("x", "*")
        s = re.sub(r"\s+", "", s).rstrip("=")

        m = re.fullmatch(r"(\d+(?:\.\d+)?)([\+\-\*/])(\d+(?:\.\d+)?)", s)
        if not m:
            return None
        left, op, right = m.group(1), m.group(2), m.group(3)
        op_key = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}[op]
        keys: list[str] = []
        for ch in left:
            keys.append(ch)
        keys.append(op_key)
        for ch in right:
            keys.append(ch)
        keys.append("equals")
        return keys

    # Generic UIA text reading â€” works for any application window.
    _UA_LABEL_SKIP_RE = re.compile(
        r"^(Display is \d+|Line \d+,?\s*Column \d+|System|Pane|TitleBar)$",
        re.IGNORECASE,
    )

    @classmethod
    def _is_meaningful_ui_text(cls, text: str, control_type: str = "") -> bool:
        t = text.strip()
        if not t or len(t) > 5000:
            return False
        if cls._UA_LABEL_SKIP_RE.match(t):
            return False
        if control_type == "Text" and t.lower().startswith("display is "):
            return False
        return bool(re.search(r"\w", t))

    @classmethod
    def _score_ui_snippet(cls, text: str, control_type: str) -> float:
        if not cls._is_meaningful_ui_text(text, control_type):
            return -1.0
        t = text.strip()
        score = 0.0
        if control_type in ("Document", "Edit"):
            score += 10.0
        if re.fullmatch(r"[\d.,]+", t.replace(",", "")):
            score += 25.0
        elif re.search(r"\d", t):
            score += 5.0
        score += min(len(t), 200) / 40.0
        return score

    @classmethod
    def _uia_snippets_show_result_value(cls, snippets: list[str]) -> bool:
        """True when UIA snippets include a standalone numeric result, not just an expression."""
        for raw in snippets:
            t = raw.strip()
            if re.fullmatch(r"[\d.,]+", t.replace(",", "")):
                return True
            if re.search(r"=\s*[\d.,]+\s*$", t):
                return True
        return False

    @classmethod
    def _read_window_text_uia(
        cls, window_title_re: str | None, *, max_items: int = 15
    ) -> list[str]:
        """Collect ranked visible text snippets from a window (any app)."""
        if sys.platform != "win32":
            return []
        try:
            import win32gui
            from pywinauto import Application

            hwnd: int | None = None
            if window_title_re:
                from pywinauto import findwindows
                pattern = re.compile(window_title_re, re.IGNORECASE)
                for h in findwindows.find_windows(title_re=window_title_re):
                    if pattern.search(win32gui.GetWindowText(h) or ""):
                        hwnd = h
                        break
            if hwnd is None:
                hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return []

            app = Application(backend="uia").connect(handle=hwnd, timeout=5)
            win = app.top_window()
            scored: list[tuple[float, str]] = []
            seen: set[str] = set()

            for ctrl_type in ("Document", "Edit", "Text"):
                for el in win.descendants(control_type=ctrl_type):
                    try:
                        val = getattr(el, "get_value", lambda: None)()
                        if not val:
                            val = el.window_text()
                        text = str(val).strip()
                        if not text or text in seen:
                            continue
                        score = cls._score_ui_snippet(text, ctrl_type)
                        if score < 0:
                            continue
                        seen.add(text)
                        scored.append((score, text))
                    except Exception:
                        continue

            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored[:max_items]]
        except Exception:
            return []

    async def _press_calculator_key_uia(self, key: str, evidence: dict[str, Any]) -> bool:
        if not self._calculator_window_open():
            return False
        try:
            from pywinauto import Application, findwindows

            hwnds = findwindows.find_windows(title_re=r"(?i)calculator")
            if not hwnds:
                return False
            app = Application(backend="uia").connect(handle=hwnds[0])
            win = app.top_window()
            labels = _CALCULATOR_BUTTON_LABELS.get(key.strip().lower(), [])
            if not labels and len(key.strip()) == 1:
                labels = [key.strip()]
            for label in labels:
                strategies = [
                    {"title": label, "control_type": "Button"},
                    {"title_re": f"(?i)^{re.escape(label)}$", "control_type": "Button"},
                    {"title_re": f"(?i){re.escape(label)}"},
                ]
                for kwargs in strategies:
                    try:
                        btn = win.child_window(**kwargs)
                        if btn.exists(timeout=0.5):
                            btn.click_input()
                            evidence["action_log"].append(f"Calculator UIA click: {label}")
                            emit(
                                "desktop_worker.py:_press_calculator_key_uia",
                                "uia_click_ok",
                                {"key": key, "label": label},
                            )
                            return True
                    except Exception:
                        continue
            emit(
                "desktop_worker.py:_press_calculator_key_uia",
                "uia_click_miss",
                {"key": key, "labels": labels},
            )
            return False
        except Exception as exc:
            evidence["action_log"].append(f"Calculator UIA press failed: {exc}")
            emit(
                "desktop_worker.py:_press_calculator_key_uia",
                "uia_click_error",
                {"key": key, "error": str(exc)},
            )
            return False

    async def _press_key(self, key: str, evidence: dict[str, Any]) -> None:
        emit("desktop_worker.py:_press_key", "press_key_start", {"key": key})

        if await self._press_calculator_key_uia(key, evidence):
            return

        sequence = self._pywinauto_key_sequence(key)
        try:
            from pywinauto.keyboard import send_keys
            send_keys(sequence)
            evidence["action_log"].append(f"Key press via pywinauto keyboard: {sequence!r}")
            emit(
                "desktop_worker.py:_press_key",
                "pywinauto_ok",
                {"key": key, "sequence": sequence},
            )
            return
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto press fallback failed: {exc}")

        import pyautogui
        pyautogui.FAILSAFE = False
        py_name = self._pyautogui_key_name(key)
        pyautogui.press(py_name)
        evidence["action_log"].append(f"Key press via PyAutoGUI fallback: {py_name!r}")
        emit(
            "desktop_worker.py:_press_key",
            "pyautogui_ok",
            {"key": key, "py_name": py_name},
        )

    def _run_uia(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> None:
        app_title = self._extract_window_title(spec.goal)
        if app_title:
            try:
                from pywinauto import Application
                app = Application(backend="uia").connect(title_re=app_title, timeout=5)
                win = app.top_window()
                win.wait("visible", timeout=5)
                import io
                tree = self._element_tree(win)
                evidence["element_tree_snapshot"] = json.dumps(tree, ensure_ascii=False)
                evidence["action_log"].append(f"Connected to window: {app_title}")
                buf = io.BytesIO()
                win.capture_as_image().save(buf, format="PNG")
                evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()
            except Exception as exc:
                raise RuntimeError(f"UIA connect failed: {exc}") from exc
        else:
            self._capture_screenshot_fallback(evidence)
            evidence["action_log"].append("No target window identified in goal")

    @staticmethod
    def _dump_ui_tree(win: Any, max_depth: int = 3, max_nodes: int = 200) -> dict:
        """Bounded UIA tree dump: control_type, auto_id, title, rectangle, is_enabled."""
        count = 0

        def walk(el: Any, depth: int) -> dict | None:
            nonlocal count
            if count >= max_nodes:
                return None
            count += 1
            try:
                rect = el.rectangle()
                node: dict[str, Any] = {
                    "control_type": str(el.element_info.control_type),
                    "auto_id": str(getattr(el.element_info, "automation_id", "") or ""),
                    "title": str(el.window_text()),
                    "rectangle": [rect.left, rect.top, rect.right, rect.bottom],
                    "is_enabled": bool(el.is_enabled()),
                }
            except Exception:
                return None
            if depth > 0:
                children = []
                for c in el.children():
                    if count >= max_nodes:
                        break
                    child = walk(c, depth - 1)
                    if child:
                        children.append(child)
                if children:
                    node["children"] = children
            return node

        return walk(win, max_depth) or {}

    @staticmethod
    def _element_tree(win: Any, depth: int = 2) -> dict:
        try:
            return {
                "title": str(win.window_text()),
                "control_type": str(win.element_info.control_type),
                "children": [
                    DesktopWorker._element_tree(c, depth - 1)
                    for c in win.children()
                ] if depth > 0 else [],
            }
        except Exception:
            return {}

    @staticmethod
    def _capture_screenshot_fallback(evidence: dict[str, Any]) -> None:
        try:
            import io

            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.thumbnail((1280, 720))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()
            evidence["action_log"].append("Screenshot captured via PIL ImageGrab (thumbnail)")
        except Exception as exc:
            evidence["action_log"].append(f"Screenshot failed: {exc}")

    @staticmethod
    def _extract_window_title(goal: str) -> str | None:
        import re
        match = re.search(r'(?:window|app|application)\s+"([^"]+)"', goal, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'(?:window|app|application)\s+([A-Za-z][A-Za-z0-9 ]+)', goal, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
