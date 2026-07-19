"""Real Playwright/MCP-tool integration against the local Slides Studio fixture."""
from __future__ import annotations

import pytest

from tests.helpers.slides_studio import start_slides_studio
from trinity_pilot.mcp import browser_server


@pytest.mark.asyncio
async def test_browser_mcp_edits_visible_slides_studio_controls():
    try:
        fixture = start_slides_studio()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    session = "slides-integration"
    try:
        try:
            opened = await browser_server.browser_open(f"{fixture.base_url}/slides", session_id=session)
        except Exception as exc:
            pytest.skip(f"Playwright Chromium is unavailable: {exc}")
        assert opened["success"] is True
        assert (await browser_server.fill("#title", "SignalDesk", session_id=session))["success"] is True
        assert (await browser_server.click("[data-theme='dark']", session_id=session))["success"] is True
        assert (await browser_server.click("#add-slide", session_id=session))["success"] is True
        audit = fixture.audit()
        assert audit["deck"]["slides"][0]["title"] == "SignalDesk"
        assert audit["deck"]["slides"][0]["theme"] == "dark"
        assert any(event["type"] == "add_slide" for event in audit["audit"])
    finally:
        await browser_server.browser_close(session)
        fixture.close()
