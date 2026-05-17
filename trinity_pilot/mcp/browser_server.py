"""FastMCP server exposing BrowserWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.browser_server
Internal hot-path skips this server and calls BrowserWorker directly.

MCP tools exposed
-----------------
High-level task tools:
  browser_navigate   — run a full agentic browser objective

Domain tools (mirrored from the inner ReAct loop):
  navigate           — navigate to a URL, return HTTP status
  click              — click a CSS selector on the current page
  fill               — fill an input field
  read_page          — read current page title, URL, and text preview

Control tools:
  finish             — signal objective complete or failed
  report_blocking    — signal an unresolvable blocker
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


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("health://browser")
def health() -> str:
    return "ok"


@mcp.resource("version://browser")
def version() -> str:
    return "0.1.0"


# ---------------------------------------------------------------------------
# High-level task tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def browser_navigate(
    objective_id: str,
    goal: str,
    success_tests: list[str],
) -> dict:
    """Navigate the browser and return evidence
    (screenshot, dom_snapshot, page_title, page_url)."""
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


# ---------------------------------------------------------------------------
# Domain tools (mirror the inner ReAct loop tools)
# These require a live Playwright page — they document the interface but
# cannot be called standalone without an active browser session.
# ---------------------------------------------------------------------------

@mcp.tool()
async def navigate(url: str) -> dict:
    """Navigate to a URL and return the resulting page URL and HTTP status.

    Note: requires an active browser session managed by BrowserWorker.
    Call browser_navigate for a fully managed session.
    """
    return {
        "note": "navigate must be called within an active BrowserWorker session.",
        "url": url,
    }


@mcp.tool()
async def click(selector: str) -> dict:
    """Click a CSS selector on the current page.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {
        "note": "click must be called within an active BrowserWorker session.",
        "selector": selector,
    }


@mcp.tool()
async def fill(selector: str, value: str) -> dict:
    """Fill an input field on the current page.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {
        "note": "fill must be called within an active BrowserWorker session.",
        "selector": selector,
        "value": value,
    }


@mcp.tool()
async def read_page() -> dict:
    """Read current page title, URL, and DOM text preview.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "read_page must be called within an active BrowserWorker session."}


# ---------------------------------------------------------------------------
# Control tools
# ---------------------------------------------------------------------------

@mcp.tool()
def finish(status: str, summary: str) -> dict:
    """Signal that the objective is complete or definitively failed.

    status: "success" | "failure"
    summary: one-paragraph description of outcome.
    """
    if status not in ("success", "failure"):
        status = "failure"
    return {"control": "finish", "status": status, "summary": summary}


@mcp.tool()
def report_blocking(reason: str, attempted: str = "") -> dict:
    """Signal an unresolvable blocker requiring orchestrator intervention."""
    return {"control": "report_blocking", "reason": reason, "attempted": attempted}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
