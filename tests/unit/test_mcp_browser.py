"""Unit tests for MCP browser server tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.mcp.browser_server import browser_navigate


_FAKE_EVIDENCE = {
    "domain": "browser",
    "objective_id": "obj-1",
    "screenshot": "",
    "dom_snapshot": "<html></html>",
    "page_title": "Example Domain",
    "page_url": "https://example.com",
    "trace_path": "",
    "error": None,
}


class TestMcpBrowserNavigate:
    async def test_browser_navigate_returns_evidence_dict(self):
        with patch(
            "trinity_pilot.mcp.browser_server.BrowserWorker.execute",
            new_callable=AsyncMock,
            return_value=_FAKE_EVIDENCE,
        ):
            result = await browser_navigate(
                objective_id="obj-1",
                goal="navigate to example.com",
                success_tests=["page title contains Example"],
            )
        assert result["page_title"] == "Example Domain"
        assert result["page_url"] == "https://example.com"
        assert result["domain"] == "browser"

    async def test_browser_navigate_passes_correct_objective_id(self):
        captured: list = []

        async def _capture(spec):
            captured.append(spec)
            return _FAKE_EVIDENCE

        with patch(
            "trinity_pilot.mcp.browser_server.BrowserWorker.execute",
            side_effect=_capture,
        ):
            await browser_navigate(
                objective_id="obj-smoke",
                goal="open google",
                success_tests=["loaded"],
            )

        assert captured[0].objective_id == "obj-smoke"
        assert captured[0].domain.value == "browser"
