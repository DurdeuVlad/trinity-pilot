"""Unit tests for MCP desktop server tools."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.mcp.desktop_server import desktop_find_window, desktop_screenshot


_FAKE_SCREENSHOT_EVIDENCE = {
    "domain": "desktop",
    "objective_id": "obj-1",
    "screenshot": "base64data",
    "element_tree_snapshot": "",
    "action_log": [],
    "degraded_mode": False,
    "error": None,
}

_FAKE_FIND_WINDOW_EVIDENCE = {
    "domain": "desktop",
    "objective_id": "obj-2",
    "screenshot": "base64data",
    "element_tree_snapshot": "<Window>Notepad</Window>",
    "action_log": [],
    "degraded_mode": False,
    "error": None,
}


class TestMcpDesktopScreenshot:
    async def test_desktop_screenshot_returns_evidence_dict(self):
        with patch(
            "trinity_pilot.mcp.desktop_server.DesktopWorker.execute",
            new_callable=AsyncMock,
            return_value=_FAKE_SCREENSHOT_EVIDENCE,
        ):
            result = await desktop_screenshot(
                objective_id="obj-1",
                goal="take a screenshot",
            )
        assert result["domain"] == "desktop"
        assert result["screenshot"] == "base64data"

    async def test_desktop_screenshot_passes_objective_id(self):
        captured: list = []

        async def _capture(spec):
            captured.append(spec)
            return _FAKE_SCREENSHOT_EVIDENCE

        with patch(
            "trinity_pilot.mcp.desktop_server.DesktopWorker.execute",
            side_effect=_capture,
        ):
            await desktop_screenshot(objective_id="obj-snap", goal="capture screen")

        assert captured[0].objective_id == "obj-snap"
        assert captured[0].domain.value == "desktop"


class TestMcpDesktopFindWindow:
    async def test_desktop_find_window_returns_evidence_dict(self):
        with patch(
            "trinity_pilot.mcp.desktop_server.DesktopWorker.execute",
            new_callable=AsyncMock,
            return_value=_FAKE_FIND_WINDOW_EVIDENCE,
        ):
            result = await desktop_find_window(
                objective_id="obj-2",
                goal="find Notepad window",
            )
        assert result["element_tree_snapshot"] == "<Window>Notepad</Window>"

    async def test_desktop_find_window_passes_correct_spec(self):
        captured: list = []

        async def _capture(spec):
            captured.append(spec)
            return _FAKE_FIND_WINDOW_EVIDENCE

        with patch(
            "trinity_pilot.mcp.desktop_server.DesktopWorker.execute",
            side_effect=_capture,
        ):
            await desktop_find_window(objective_id="obj-win", goal="find window")

        assert captured[0].objective_id == "obj-win"
        assert "element_tree_snapshot" in captured[0].evidence_bundle
