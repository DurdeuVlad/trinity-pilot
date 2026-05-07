"""FastMCP server exposing BrowserWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.browser_server
Internal hot-path skips this server and calls BrowserWorker directly.
"""
from __future__ import annotations

from fastmcp import FastMCP

from trinity_pilot.core.types import (
    DomainType,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.workers.browser_worker import BrowserWorker

mcp = FastMCP(
    name="trinity-pilot-browser",
    version="0.1.0",
)


@mcp.resource("health://browser")
def health() -> str:
    return "ok"


@mcp.resource("version://browser")
def version() -> str:
    return "0.1.0"


@mcp.tool()
async def browser_navigate(
    objective_id: str,
    goal: str,
    success_tests: list[str],
) -> dict:
    """Navigate the browser and return evidence (screenshot, dom_snapshot, page_title, page_url)."""
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=success_tests,
        evidence_bundle=["screenshot", "dom_snapshot", "page_title", "page_url"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    worker = BrowserWorker()
    return await worker.execute(spec)


if __name__ == "__main__":
    mcp.run()
