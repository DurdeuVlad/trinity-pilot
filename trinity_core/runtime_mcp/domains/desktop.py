"""Desktop domain MCP server."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from trinity_core.runtime_mcp.base import TrinityMCPServer
from trinity_core.tools.desktop_tools import build_desktop_tools


class DesktopMCPServer(TrinityMCPServer):

    @property
    def domain(self) -> str:
        return "desktop"

    @property
    def server_name(self) -> str:
        return "trinity-desktop-toolset"

    @property
    def display_name(self) -> str:
        return "Trinity Desktop Toolset"

    def _max_output_chars(self) -> int:
        return 64_000  # desktop screenshots have large metadata payloads

    def instructions(self) -> str:
        return """\
Trinity Desktop Toolset -- pywinauto-based Windows UI automation.

CAPABILITIES: Window management, control interaction (click, type, select),
element inspection, screenshot, focus/unfocus, keyboard shortcuts.

CONSTRAINTS:
- Serial execution; UI state is globally shared
- Target application must be visible and not minimized
- DPI-aware; coordinates scale with display DPI setting
- pywinauto wraps Win32/UIA; some UWP apps may be inaccessible

GUIDANCE:
- Inspect window hierarchy and find the correct window before acting
- Focus the window before typing or clicking controls
- Use wait tools to confirm apps, windows, and UI elements before acting
- Verify visible window titles or elements after meaningful desktop actions

FORBIDDEN:
- Do not use raw coordinates without prior element verification
- Do not use CLI tools to simulate desktop shortcuts in a desktop objective
- Do not interact with a window that is not foreground/focused

WINDOW TITLE MATCHING RULES:
pywinauto matches window titles using Python regex (substring search, case-insensitive).

Rules:
- NEVER use a leading wildcard: "*Notepad" is invalid regex (asterisk needs a preceding char).
  Use "Notepad" -- it will match "Untitled - Notepad" and "Notepad" automatically.
- NEVER use glob syntax: "*.txt", "*Notepad*" -- these are not valid regex.
- Date-prefixed titles like "2026-04-27 - Notepad": match on "Notepad" alone, not the date prefix.
  The date changes every day and is irrelevant for matching.
- Dots in titles are regex wildcards: "file.txt" matches "filextxt". Escape with "file\\.txt" if literal.
- Parentheses and brackets need escaping if literal: use "\\(" not "(" in title patterns.
- Prefer the shortest stable substring: "Notepad" over "Untitled - Notepad" (title changes with file).

Valid examples:
  focus_window("Notepad")          -- matches "Untitled - Notepad", "file.txt - Notepad"
  focus_window("Calculator")       -- matches "Calculator"
  focus_window("Chrome")           -- matches any Chrome window
  wait_for_window("Notepad")       -- correct

Invalid examples (will fail or match wrong window):
  focus_window("*Notepad")         -- leading * breaks regex
  focus_window("*Notepad*")        -- leading * breaks regex
  focus_window("2026-04-27 - Notepad")  -- date prefix changes daily, fragile match

ELEMENT PATTERNS:
- Element names are matched case-insensitively as substring or exact strings.
- Prefer short partial names: "Edit" not "Edit1", "OK" not "Button OK".
- If a control has an auto-generated name like "Edit0", inspect siblings to find a stable label.

OPEN_APP RULES:
- If open_app returns was_existing: true, the app was already running. The active_window
  shown is the correct target. Do NOT call open_app again. Do NOT call focus again if
  focus already succeeded. Proceed with your next action immediately.
- If open_app returns was_existing: false, a fresh window was opened. Use active_window
  as your target for subsequent focus/click/type calls.
- A Notepad window showing a dated filename (e.g. "2026-04-27 - Notepad") IS a valid
  Notepad window. The task "open Notepad" is complete when any Notepad window is focused,
  regardless of what document it shows.

REORIENTATION:
- If you are uncertain about what is on screen, call list_windows to see all open window
  titles before retrying any action.
- If get_focused_window returns a title matching your target app, the window is already
  focused — do not call focus again.
"""

    def tool_guides(self) -> dict[str, str]:
        return {
            "general": "Inspect window hierarchy first, then focus and act.",
            "inspect": "Use find_window, list_controls, get_window_text -- read-only.",
            "mutate": "Focus window, then click/type/select -- verify element state after.",
            "wait": "Use wait_for_window or wait_for_element before acting on app state.",
            "verify": "Read window title or control value after action to confirm change.",
            "recover": "Re-inspect hierarchy; app may have redrawn or focus may have shifted.",
        }

    def recovery_guides(self) -> dict[str, str]:
        return {
            "default": "Re-inspect window hierarchy, re-focus, and retry.",
            "WINDOW_NOT_FOUND": "App may not be running or window title changed. Find window first.",
            "CONTROL_NOT_FOUND": "Control may be hidden or renamed. Re-inspect parent window controls.",
            "FOCUS_FAILED": "Window not responding to focus. Check if it is minimized or blocked.",
            "ELEMENT_NOT_VISIBLE": "Element exists but not visible. Scroll into view or resize window.",
        }

    def forbidden_patterns(self) -> str:
        return """\
- Do not use raw screen coordinates without first verifying element position
- Do not use CLI tools to simulate keyboard shortcuts in a desktop objective
- Do not interact with a non-foreground or minimized window
- Do not skip wait conditions when launching applications that load slowly
"""

    def constraint_summaries(self) -> list[str]:
        return [
            "pywinauto / Win32 / UIA; some UWP apps inaccessible",
            "Serial execution -- globally shared UI state",
            "DPI-aware coordinates",
            "Target window must be visible and not minimized",
        ]

    def example_tasks(self) -> list[str]:
        return [
            "Open Notepad and type text into the editor",
            "Click a button in a running desktop application",
            "Read the text content of a window's control",
            "Close an application via its window controls",
        ]

    def domain_metadata(self) -> dict[str, Any]:
        return {
            "serial_execution": True,
            "parallel_safe": False,
            "underlying_tech": "pywinauto / Win32 / UIA",
        }

    def register_tools(self, mcp: FastMCP) -> None:
        self._register_trinity_tools(mcp, build_desktop_tools())
