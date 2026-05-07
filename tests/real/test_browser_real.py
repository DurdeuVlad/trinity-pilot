"""Real browser test — hits live https://example.com via BrowserWorker directly."""
import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.browser_worker import BrowserWorker

pytestmark = pytest.mark.real


@pytest.fixture
def browser_spec():
    return ObjectiveSpec(
        objective_id="real-browser-1",
        goal="navigate to https://example.com",
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=["chromium installed"],
        success_tests=["page title contains 'Example'"],
        evidence_bundle=["screenshot", "dom_snapshot", "page_title", "page_url"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


async def test_navigate_returns_evidence(browser_spec):
    worker = BrowserWorker()
    evidence = await worker.execute(browser_spec)

    assert evidence["domain"] == "browser"
    assert evidence["page_title"] is not None
    assert "example" in evidence["page_title"].lower()
    assert evidence["page_url"].startswith("https://example.com")
    assert evidence["screenshot"] is not None
    assert len(evidence["screenshot"]) > 100  # non-empty base64
    assert evidence["dom_snapshot"] is not None


async def test_navigate_captures_dom_snapshot(browser_spec):
    worker = BrowserWorker()
    evidence = await worker.execute(browser_spec)

    assert "<html" in evidence["dom_snapshot"].lower()
