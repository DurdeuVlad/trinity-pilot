"""Unit tests for MCP browser server tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.mcp.browser_server import browser_navigate
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.worker_result import WorkerResult


def _spec_dict(objective_id: str = "obj-1", goal: str = "navigate to example.com",
                success_tests: list[str] | None = None) -> dict:
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=success_tests or ["page title contains Example"],
        evidence_bundle=["screenshot", "dom_snapshot", "page_title", "page_url"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    return spec.to_dict()


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


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


class TestMcpBrowserNavigate:
    async def test_browser_navigate_returns_evidence_dict(self):
        with patch(
            "trinity_pilot.mcp.browser_server.BrowserWorker.execute",
            new_callable=AsyncMock,
            return_value=_FAKE_EVIDENCE,
        ):
            result = await browser_navigate(_spec_dict())
        assert result["mcp_status"] == "ok"
        assert result["evidence"]["page_title"] == "Example Domain"
        assert result["evidence"]["page_url"] == "https://example.com"
        assert result["evidence"]["domain"] == "browser"

    async def test_browser_navigate_passes_correct_objective_id(self):
        captured: list = []

        async def _capture(spec):
            captured.append(spec)
            return _FAKE_EVIDENCE

        with patch(
            "trinity_pilot.mcp.browser_server.BrowserWorker.execute",
            side_effect=_capture,
        ):
            await browser_navigate(_spec_dict(objective_id="obj-smoke", goal="open google",
                                               success_tests=["loaded"]))

        assert captured[0].objective_id == "obj-smoke"
        assert captured[0].domain.value == "browser"

    async def test_browser_navigate_translates_worker_blocker(self):
        worker_result = WorkerResult(
            status="blocked", summary="needs confirmation", evidence={},
            steps_taken=2, tokens_used=10,
        )
        with patch(
            "trinity_pilot.mcp.browser_server.BrowserWorker.execute",
            side_effect=WorkerBlocker("confirmation required", worker_result),
        ):
            result = await browser_navigate(_spec_dict())
        assert result["mcp_status"] == "blocker"
        assert result["reason"] == "confirmation required"
        assert result["result"]["status"] == "blocked"

    async def test_browser_navigate_translates_worker_error(self):
        with patch(
            "trinity_pilot.mcp.browser_server.BrowserWorker.execute",
            side_effect=WorkerError("boom"),
        ):
            result = await browser_navigate(_spec_dict())
        assert result["mcp_status"] == "error"
        assert result["message"] == "boom"
