"""FastMCP server exposing BrowserWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.browser_server
Internal hot-path skips this server and calls BrowserWorker directly.

MCP tools exposed
-----------------
High-level task tools:
  browser_navigate   — run a full agentic browser objective

Domain sensor tools (read-only, browser-specific — require active session):
  read_page          — read current page title, URL, and text preview
  dom_snapshot       — full DOM as structured text
  accessibility_tree — ARIA accessibility tree of current page
  current_url        — active page URL
  page_title         — active page title
  get_cookies        — cookies for current session or domain
  list_open_tabs     — all open browser tabs
  network_log        — recent network requests
  get_element_text   — text content of a CSS-selected element
  get_element_attribute — attribute value of a CSS-selected element

Domain action tools (mirrored from the inner ReAct loop):
  navigate           — navigate to a URL, return HTTP status
  click              — click a CSS selector on the current page
  fill               — fill an input field

Control tools:
  finish             — signal objective complete or failed
  report_blocking    — signal an unresolvable blocker
"""
from __future__ import annotations

from fastmcp import FastMCP

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.mcp.tool_registry import ToolManifest, ToolMetadata
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.browser_worker import BrowserWorker

mcp = FastMCP(
    name="trinity-pilot-browser",
    version="0.1.0",
)

SERVER_NAME = "trinity-pilot-browser"

TOOL_MANIFEST: ToolManifest = (
    ToolMetadata("browser_navigate", SERVER_NAME, "task", "Run a full browser objective."),
    ToolMetadata("navigate", SERVER_NAME, "action", "Navigate the active browser page."),
    ToolMetadata("click", SERVER_NAME, "action", "Click a CSS selector on the active page."),
    ToolMetadata("fill", SERVER_NAME, "action", "Fill an input on the active page."),
    ToolMetadata("read_page", SERVER_NAME, "sensor", "Read page title, URL, and text preview."),
    ToolMetadata("dom_snapshot", SERVER_NAME, "sensor", "Read the current page DOM."),
    ToolMetadata("accessibility_tree", SERVER_NAME, "sensor", "Read the page accessibility tree."),
    ToolMetadata("current_url", SERVER_NAME, "sensor", "Read the active page URL."),
    ToolMetadata("page_title", SERVER_NAME, "sensor", "Read the active page title."),
    ToolMetadata("get_cookies", SERVER_NAME, "sensor", "Read browser cookies."),
    ToolMetadata("list_open_tabs", SERVER_NAME, "sensor", "Read open browser tab metadata."),
    ToolMetadata("network_log", SERVER_NAME, "sensor", "Read recent network request metadata."),
    ToolMetadata("get_element_text", SERVER_NAME, "sensor", "Read text from a CSS-selected element."),
    ToolMetadata("get_element_attribute", SERVER_NAME, "sensor", "Read an element attribute."),
    ToolMetadata("finish", SERVER_NAME, "control", "Signal objective completion."),
    ToolMetadata("report_blocking", SERVER_NAME, "control", "Signal an unresolvable blocker."),
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
async def browser_navigate(spec_dict: dict) -> dict:
    """Execute a full browser objective and return a tagged result envelope.

    spec_dict is ObjectiveSpec.to_dict() — the complete objective spec,
    including metadata (retry_context, steering_context, dependency_evidence,
    timeout_seconds), dependencies, max_attempts, risk_class, etc. This is the
    real dispatch boundary: a fresh BrowserWorker is constructed per call.

    Returns one of three tagged shapes (WorkerBlocker/WorkerError cannot cross
    the MCP JSON-RPC boundary as raised exceptions, so they are translated):
      {"mcp_status": "ok", "evidence": {...}}
      {"mcp_status": "blocker", "reason": str, "result": {status, summary,
                                            evidence, steps_taken, tokens_used}}
      {"mcp_status": "error", "message": str}
    """
    spec = ObjectiveSpec.from_dict(spec_dict)
    worker = BrowserWorker()
    try:
        evidence = await worker.execute(spec)
        return {"mcp_status": "ok", "evidence": evidence}
    except WorkerBlocker as exc:
        result = exc.result
        return {
            "mcp_status": "blocker",
            "reason": str(exc),
            "result": {
                "status": result.status,
                "summary": result.summary,
                "evidence": result.evidence,
                "steps_taken": result.steps_taken,
                "tokens_used": result.tokens_used,
            },
        }
    except WorkerError as exc:
        return {"mcp_status": "error", "message": str(exc)}


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
# Domain sensor tools (browser-specific, require active session)
# ---------------------------------------------------------------------------

@mcp.tool()
async def dom_snapshot() -> dict:
    """Return the full DOM as structured text (elements, attributes, text nodes).

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "dom_snapshot must be called within an active BrowserWorker session."}


@mcp.tool()
async def accessibility_tree() -> dict:
    """Return the ARIA accessibility tree of the current page.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "accessibility_tree must be called within an active BrowserWorker session."}


@mcp.tool()
async def current_url() -> dict:
    """Return the active page URL.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "current_url must be called within an active BrowserWorker session."}


@mcp.tool()
async def page_title() -> dict:
    """Return the active page title.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "page_title must be called within an active BrowserWorker session."}


@mcp.tool()
async def get_cookies(domain: str = "") -> dict:
    """Return cookies for the current session or a specific domain.

    Args:
        domain: Optional domain to filter cookies (e.g. 'example.com').

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "get_cookies must be called within an active BrowserWorker session.", "domain": domain}


@mcp.tool()
async def list_open_tabs() -> dict:
    """Return all open browser tabs with title and URL.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "list_open_tabs must be called within an active BrowserWorker session."}


@mcp.tool()
async def network_log(limit: int = 20) -> dict:
    """Return recent network requests: method, URL, status code.

    Args:
        limit: Maximum number of recent entries to return.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "network_log must be called within an active BrowserWorker session.", "limit": limit}


@mcp.tool()
async def get_element_text(selector: str) -> dict:
    """Return text content of a CSS-selected element.

    Args:
        selector: CSS selector for the target element.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "get_element_text must be called within an active BrowserWorker session.", "selector": selector}


@mcp.tool()
async def get_element_attribute(selector: str, attr: str) -> dict:
    """Return an attribute value of a CSS-selected element.

    Args:
        selector: CSS selector for the target element.
        attr: Attribute name (e.g. 'href', 'value', 'class').

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"note": "get_element_attribute must be called within an active BrowserWorker session.", "selector": selector, "attr": attr}


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
