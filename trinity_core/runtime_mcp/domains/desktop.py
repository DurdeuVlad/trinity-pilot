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
