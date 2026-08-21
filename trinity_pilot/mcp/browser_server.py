"""FastMCP server exposing BrowserWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.browser_server

Product path is MCP-only: the orchestrator always dispatches via MCPClientPool
(there is no hot-path that skips this server).

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

import base64
from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP

from trinity_pilot import __version__
from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.mcp.base_server import ControlState
from trinity_pilot.mcp.tool_registry import ToolManifest, ToolMetadata
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.browser_worker import BrowserWorker

mcp = FastMCP(
    name="trinity-pilot-browser",
    version=__version__,
)

SERVER_NAME = "trinity-pilot-browser"


@dataclass
class _BrowserSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    network: list[dict[str, str]] = field(default_factory=list)


_sessions: dict[str, _BrowserSession] = {}
_control = ControlState()


async def _session(session_id: str = "default") -> _BrowserSession:
    session = _sessions.get(session_id)
    if session is None:
        raise RuntimeError(f"Browser session '{session_id}' is not open; call browser_open first.")
    return session


def _action(success: bool, action: str, result: str, observation: dict | None = None, error: str | None = None) -> dict:
    return {"success": success, "action": action, "result": result, "observation": observation or {}, "error": error}


async def _observation(page: Any, screenshot: bool = False) -> dict:
    observation = {"current_url": page.url, "page_title": await page.title()}
    if screenshot:
        observation["screenshot_b64"] = base64.b64encode(await page.screenshot()).decode("ascii")
    return observation

TOOL_MANIFEST: ToolManifest = (
    ToolMetadata("browser_navigate", SERVER_NAME, "task", "Run a full browser objective."),
    ToolMetadata("browser_open", SERVER_NAME, "task", "Open a managed browser session."),
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
    ToolMetadata("screenshot", SERVER_NAME, "sensor", "Capture the current page."),
    ToolMetadata("wait_for_selector", SERVER_NAME, "sensor", "Wait for a selector."),
    ToolMetadata("evaluate_js", SERVER_NAME, "sensor", "Evaluate page JavaScript."),
    ToolMetadata("browser_close", SERVER_NAME, "control", "Close a browser session."),
    ToolMetadata("todo_write", SERVER_NAME, "control", "Replace the current todo list."),
    ToolMetadata("todo_read", SERVER_NAME, "control", "Read the current todo list."),
    ToolMetadata("todo_check", SERVER_NAME, "control", "Complete a todo item."),
    ToolMetadata("todo_add", SERVER_NAME, "control", "Append a todo item."),
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
    return __version__


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
async def browser_open(url: str = "about:blank", session_id: str = "default", headless: bool = True) -> dict:
    """Open an isolated Playwright browser session and optionally navigate it."""
    await browser_close(session_id)
    from playwright.async_api import async_playwright
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=headless)
    except Exception:
        # Launch can fail before a browser/context exists (for example when a
        # Playwright package was installed without its Chromium binary). Do not
        # leak the Node transport in that failure path.
        await playwright.stop()
        raise
    context = await browser.new_context()
    page = await context.new_page()
    session = _BrowserSession(playwright, browser, context, page)
    session.network.append({"method": "GET", "url": url, "status": "pending"})
    page.on("request", lambda request: session.network.append({"method": request.method, "url": request.url, "status": "pending"}))
    page.on("response", lambda response: session.network.append({"method": response.request.method, "url": response.url, "status": str(response.status)}))
    _sessions[session_id] = session
    if url and url != "about:blank":
        response = await page.goto(url)
        return _action(True, "open browser", f"opened {page.url}", {**await _observation(page, True), "status": response.status if response else None})
    return _action(True, "open browser", "opened blank page", await _observation(page))


@mcp.tool()
async def navigate(url: str, session_id: str = "default") -> dict:
    """Navigate an existing browser session."""
    try:
        page = (await _session(session_id)).page
        response = await page.goto(url)
        return _action(True, "navigate", f"navigated to {page.url}", {**await _observation(page, True), "status": response.status if response else None})
    except Exception as exc:
        return _action(False, "navigate", "navigation failed", error=str(exc))


@mcp.tool()
async def click(selector: str, session_id: str = "default") -> dict:
    """Click a CSS selector on the current page.

    Note: requires an active browser session managed by BrowserWorker.
    """
    try:
        page = (await _session(session_id)).page
        await page.locator(selector).click()
        return _action(True, "click", f"clicked {selector}", await _observation(page, True))
    except Exception as exc:
        return _action(False, "click", f"could not click {selector}", error=str(exc))


@mcp.tool()
async def fill(selector: str, value: str, session_id: str = "default") -> dict:
    """Fill an input field on the current page.

    Note: requires an active browser session managed by BrowserWorker.
    """
    try:
        page = (await _session(session_id)).page
        await page.locator(selector).fill(value)
        return _action(True, "fill", f"filled {selector}", await _observation(page))
    except Exception as exc:
        return _action(False, "fill", f"could not fill {selector}", error=str(exc))


@mcp.tool()
async def read_page(session_id: str = "default") -> dict:
    """Read current page title, URL, and DOM text preview.

    Note: requires an active browser session managed by BrowserWorker.
    """
    page = (await _session(session_id)).page
    return {**await _observation(page), "text": (await page.locator("body").inner_text())[:10000]}


# ---------------------------------------------------------------------------
# Domain sensor tools (browser-specific, require active session)
# ---------------------------------------------------------------------------

@mcp.tool()
async def dom_snapshot(session_id: str = "default") -> dict:
    """Return the full DOM as structured text (elements, attributes, text nodes).

    Note: requires an active browser session managed by BrowserWorker.
    """
    page = (await _session(session_id)).page
    return {"html": await page.content(), "url": page.url}


@mcp.tool()
async def accessibility_tree(session_id: str = "default") -> dict:
    """Return the ARIA accessibility tree of the current page.

    Note: requires an active browser session managed by BrowserWorker.
    """
    page = (await _session(session_id)).page
    return {"accessibility_tree": await page.locator("body").aria_snapshot()}


@mcp.tool()
async def current_url(session_id: str = "default") -> dict:
    """Return the active page URL.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"url": (await _session(session_id)).page.url}


@mcp.tool()
async def page_title(session_id: str = "default") -> dict:
    """Return the active page title.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"title": await (await _session(session_id)).page.title()}


@mcp.tool()
async def get_cookies(domain: str = "", session_id: str = "default") -> dict:
    """Return cookies for the current session or a specific domain.

    Args:
        domain: Optional domain to filter cookies (e.g. 'example.com').

    Note: requires an active browser session managed by BrowserWorker.
    """
    cookies = await (await _session(session_id)).context.cookies()
    if domain:
        cookies = [cookie for cookie in cookies if domain in cookie.get("domain", "")]
    return {"cookies": cookies}


@mcp.tool()
async def list_open_tabs(session_id: str = "default") -> dict:
    """Return all open browser tabs with title and URL.

    Note: requires an active browser session managed by BrowserWorker.
    """
    context = (await _session(session_id)).context
    return {"tabs": [{"url": page.url, "title": await page.title()} for page in context.pages]}


@mcp.tool()
async def network_log(limit: int = 20, session_id: str = "default") -> dict:
    """Return recent network requests: method, URL, status code.

    Args:
        limit: Maximum number of recent entries to return.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"requests": (await _session(session_id)).network[-max(0, limit):]}


@mcp.tool()
async def get_element_text(selector: str, session_id: str = "default") -> dict:
    """Return text content of a CSS-selected element.

    Args:
        selector: CSS selector for the target element.

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"text": await (await _session(session_id)).page.locator(selector).inner_text()}


@mcp.tool()
async def get_element_attribute(selector: str, attr: str, session_id: str = "default") -> dict:
    """Return an attribute value of a CSS-selected element.

    Args:
        selector: CSS selector for the target element.
        attr: Attribute name (e.g. 'href', 'value', 'class').

    Note: requires an active browser session managed by BrowserWorker.
    """
    return {"value": await (await _session(session_id)).page.locator(selector).get_attribute(attr)}


@mcp.tool()
async def screenshot(session_id: str = "default") -> dict:
    """Capture the active page as base64 PNG."""
    return {"screenshot_b64": base64.b64encode(await (await _session(session_id)).page.screenshot()).decode("ascii")}


@mcp.tool()
async def wait_for_selector(selector: str, timeout: int = 5000, session_id: str = "default") -> dict:
    await (await _session(session_id)).page.locator(selector).wait_for(timeout=timeout)
    return {"found": True, "selector": selector}


@mcp.tool()
async def evaluate_js(script: str, session_id: str = "default") -> dict:
    return {"value": await (await _session(session_id)).page.evaluate(script)}


@mcp.tool()
async def browser_close(session_id: str = "default") -> dict:
    session = _sessions.pop(session_id, None)
    if session is None:
        return {"closed": False, "session_id": session_id}
    await session.context.close()
    await session.browser.close()
    await session.playwright.stop()
    return {"closed": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Control tools
# ---------------------------------------------------------------------------

@mcp.tool()
def todo_write(items: list[str], session_id: str = "default") -> dict:
    return _control.write(items, session_id)


@mcp.tool()
def todo_read(session_id: str = "default") -> dict:
    return _control.read(session_id)


@mcp.tool()
def todo_check(index: int, session_id: str = "default") -> dict:
    return _control.check(index, session_id)


@mcp.tool()
def todo_add(item: str, session_id: str = "default") -> dict:
    return _control.add(item, session_id)

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
