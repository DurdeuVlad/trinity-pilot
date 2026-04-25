"""Browser domain MCP server."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from trinity_core.runtime_mcp.base import TrinityMCPServer
from trinity_core.tools.browser_tools import build_browser_tools


class BrowserMCPServer(TrinityMCPServer):

    @property
    def domain(self) -> str:
        return "web"

    @property
    def server_name(self) -> str:
        return "trinity-web-toolset"

    @property
    def display_name(self) -> str:
        return "Trinity Browser Toolset"

    def instructions(self) -> str:
        return """\
Trinity Browser Toolset -- Playwright-backed Chromium automation.

CAPABILITIES: Navigation, DOM inspection, clicking, typing, screenshots,
wait conditions, form submission, JS evaluation.

CONSTRAINTS:
- Shared Chromium session; navigation state persists across calls
- Cannot run shell commands or interact with desktop windows
- Selectors: CSS or XPath, prefer CSS

GUIDANCE:
- Read before mutate: screenshot / inspect before click / type
- Use wait tools instead of retry loops on stale pages
- Verify URL and visible text after navigation or form submission

FORBIDDEN:
- Do not fall back to CLI or desktop to recover browser objectives
- Do not run arbitrary JS except via the evaluate_js tool
"""

    def tool_guides(self) -> dict[str, str]:
        return {
            "general": "Use screenshot or inspect_element to understand current page state.",
            "inspect": "Use get_text, inspect_element, screenshot -- none mutate state.",
            "mutate": "Use navigate, click_element, type_text -- verify after each.",
            "wait": "Use wait_for_element or wait_for_navigation before acting on dynamic content.",
            "verify": "Use get_current_url, get_text, or screenshot to confirm completion.",
            "recover": "Screenshot -> re-inspect -> try alternative selector.",
        }

    def recovery_guides(self) -> dict[str, str]:
        return {
            "default": "Take screenshot, inspect page state, retry with adjusted params.",
            "SELECTOR_NOT_FOUND": "Element not found. Screenshot, find visible alternative selector.",
            "NAVIGATION_TIMEOUT": "Page timed out. Check URL, try wait_for_navigation.",
            "ELEMENT_NOT_INTERACTABLE": "Element exists but not clickable. Scroll into view or wait.",
        }

    def forbidden_patterns(self) -> str:
        return """\
- Do not fall back to CLI or desktop to recover a browser objective
- Do not run arbitrary JavaScript unless using evaluate_js explicitly
- Do not retry the same failing selector twice without inspecting state
- Do not assume navigation completed without verifying URL or page content
"""

    def constraint_summaries(self) -> list[str]:
        return [
            "Playwright-backed Chromium; shared session per task",
            "No shell or desktop access",
            "CSS/XPath selectors only",
            "Parallel execution safe",
        ]

    def example_tasks(self) -> list[str]:
        return [
            "Navigate to https://example.com and extract the page title",
            "Fill in a login form and submit it",
            "Wait for a dynamic element to appear and click it",
            "Take a screenshot to verify page state",
        ]

    def domain_metadata(self) -> dict[str, Any]:
        return {
            "serial_execution": False,
            "parallel_safe": True,
            "underlying_tech": "Playwright / Chromium",
        }

    def register_tools(self, mcp: FastMCP) -> None:
        self._register_trinity_tools(mcp, build_browser_tools())
