"""Browser worker unit tests — mocks Playwright at playwright.async_api level."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.browser_worker import BrowserWorker


def _spec(goal: str = "navigate to https://example.com") -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-browser",
        goal=goal,
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["page title contains 'Example'"],
        evidence_bundle=["screenshot", "dom_snapshot", "page_title", "page_url"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


def _make_mock_context():
    """Build a mock playwright async_playwright() context manager stack."""
    mock_page = AsyncMock()
    mock_page.title = AsyncMock(return_value="Example Domain")
    mock_page.url = "https://example.com"
    mock_page.content = AsyncMock(return_value="<html/>")
    mock_page.screenshot = AsyncMock(return_value=b"fake-png")
    mock_page.goto = AsyncMock()

    mock_tracing = AsyncMock()
    mock_tracing.start = AsyncMock()
    mock_tracing.stop = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.pages = [mock_page]
    mock_browser.tracing = mock_tracing
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_browser)

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw.__aexit__ = AsyncMock(return_value=False)

    mock_ap_cm = MagicMock()
    mock_ap_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_ap_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_ap_cm, mock_page, mock_browser


class TestBrowserWorker:
    async def test_returns_expected_evidence_keys(self):
        mock_ap_cm, mock_page, mock_browser = _make_mock_context()

        with patch("playwright.async_api.async_playwright", return_value=mock_ap_cm):
            worker = BrowserWorker()
            evidence = await worker.execute(_spec())

        assert "screenshot" in evidence
        assert "dom_snapshot" in evidence
        assert "page_title" in evidence
        assert "page_url" in evidence
        assert evidence["domain"] == "browser"
        assert evidence["objective_id"] == "obj-browser"

    async def test_navigate_calls_page_goto(self):
        mock_ap_cm, mock_page, mock_browser = _make_mock_context()

        with patch("playwright.async_api.async_playwright", return_value=mock_ap_cm):
            worker = BrowserWorker()
            await worker.execute(_spec("navigate to https://example.com"))

        mock_page.goto.assert_called_once()
        call_args = mock_page.goto.call_args
        assert "https://example.com" in call_args.args[0]

    async def test_screenshot_base64_encoded(self):
        mock_ap_cm, mock_page, mock_browser = _make_mock_context()
        mock_page.screenshot = AsyncMock(return_value=b"raw-bytes")

        with patch("playwright.async_api.async_playwright", return_value=mock_ap_cm):
            worker = BrowserWorker()
            evidence = await worker.execute(_spec())

        expected = base64.b64encode(b"raw-bytes").decode()
        assert evidence["screenshot"] == expected

    def test_extract_url_finds_https(self):
        assert BrowserWorker._extract_url("navigate to https://example.com/path") == "https://example.com/path"

    def test_extract_url_returns_none_if_missing(self):
        assert BrowserWorker._extract_url("open the browser") is None

    async def test_timeout_raises_worker_error(self):
        import asyncio

        async def slow_inner(spec, evidence):
            await asyncio.sleep(999)

        worker = BrowserWorker()
        worker._execute_inner = slow_inner  # type: ignore

        spec = _spec()
        spec.metadata["timeout_seconds"] = 0.01

        with pytest.raises(WorkerError, match="[Tt]imeout"):
            await worker.execute(spec)
