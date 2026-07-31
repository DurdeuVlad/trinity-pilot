from __future__ import annotations

import asyncio
import base64
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _BlockerSignal,
    _finish_decl,
    _FinishSignal,
    _make_tool,
    _report_blocking_decl,
    _take_screenshot_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_BROWSER_AGENT_SYSTEM = """\
You are a browser automation agent using Playwright on a live browser.
Use the available tools to accomplish the goal step by step.

Tool categories:
- SENSOR tools read, inspect, measure, and detect. They never change world state.
  Use them freely before and after actions to verify state.
- ACTION tools create, modify, execute, or delete. They change world state.
  Each action must be intentional. Prefer sensing first, then acting.

Available tools:

[SENSOR] screenshot: Capture current desktop as PNG visual evidence. mode='screen' (default), 'all_screens', or 'app' (supply app_title regex).
[SENSOR] read_page: Read current page title, URL, and DOM text preview.
[SENSOR] read_text: Read the visible text of one CSS selector.
[SENSOR] read_elements: Enumerate all elements matching a selector with 0-based indices.
[SENSOR] get_attribute: Read one HTML attribute's value from an element.
[SENSOR] wait_for: Wait for a selector state or network idle before proceeding.
[SENSOR] list_tabs: List all open tabs/pages with their index, title, and URL.
[SENSOR] network_requests: Read recently observed network responses (url, status, method).

[ACTION] navigate: Navigate to a URL.
[ACTION] click: Click a CSS selector on the current page. Optional nth (0-based) to pick among multiple matches.
[ACTION] fill: Fill an input field on the current page. Optional nth (0-based) to pick among multiple matches.
[ACTION] select_option: Select an option in a <select> element by value or label.
[ACTION] set_checked: Check or uncheck a checkbox/radio input.
[ACTION] scroll: Scroll an element into view, or scroll the viewport by a pixel delta.
[ACTION] navigate_history: Go back or forward in browser history.
[ACTION] hover: Hover the mouse over an element.
[ACTION] handle_dialog: Pre-arm accept/dismiss for the next dialog before the action that triggers it.
[ACTION] switch_tab: Switch the active tab/page by index (see list_tabs).
[ACTION] file_upload: Upload a local file into a file input element.
[ACTION] evaluate_js: Run arbitrary JavaScript in the page context (escape hatch — use sparingly).
[ACTION] finish: Signal that the objective is complete or definitively failed.
[ACTION] report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

RULES:
- Always navigate to a URL first before interacting with elements.
- After each ACTION tool call, read its result before proceeding. If a tool failed or
  produced unexpected state, adapt — do not blindly continue to the next planned step.
- Call wait_for after navigation or actions that trigger dynamic content (SPAs, XHR-driven
  updates) before reading or acting on the page — read_page/click can otherwise race the DOM.
- Call handle_dialog BEFORE an action you expect to trigger a JS alert/confirm/prompt; dialogs
  are auto-dismissed if not pre-armed.
- If a link or button opens a new tab/popup, call list_tabs then switch_tab to continue there.
- Call screenshot after key actions to verify the result visually.
- Call finish when done or if the objective is definitively impossible.
- Call report_blocking only if you genuinely cannot proceed without external input.
"""

# Domain tool declarations
_navigate_decl = genai_types.FunctionDeclaration(
    name="navigate",
    description="Navigate the browser to a URL.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "url": genai_types.Schema(type=genai_types.Type.STRING, description="The URL to navigate to."),
        },
        required=["url"],
    ),
)

_click_decl = genai_types.FunctionDeclaration(
    name="click",
    description="Click a CSS selector on the current page.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector to click."),
            "nth": genai_types.Schema(type=genai_types.Type.INTEGER, description="0-based index when selector matches multiple elements (default 0)."),
        },
        required=["selector"],
    ),
)

_fill_decl = genai_types.FunctionDeclaration(
    name="fill",
    description="Fill an input field on the current page.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector to fill."),
            "value": genai_types.Schema(type=genai_types.Type.STRING, description="Value to fill."),
            "nth": genai_types.Schema(type=genai_types.Type.INTEGER, description="0-based index when selector matches multiple elements (default 0)."),
        },
        required=["selector", "value"],
    ),
)

_read_page_decl = genai_types.FunctionDeclaration(
    name="read_page",
    description="Returns current page title, URL, and DOM text preview.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={},
    ),
)

_read_text_decl = genai_types.FunctionDeclaration(
    name="read_text",
    description="Read the visible text content of a CSS selector on the current page.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="CSS selector for the element whose text should be read.",
            ),
        },
        required=["selector"],
    ),
)

_wait_for_decl = genai_types.FunctionDeclaration(
    name="wait_for",
    description=(
        "Wait for a condition on the page before proceeding: a selector to reach a state, "
        "or the network to go idle."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector to wait for (omit to wait on network only)."),
            "state": genai_types.Schema(type=genai_types.Type.STRING, description="Selector state to wait for.", enum=["attached", "detached", "visible", "hidden"]),
            "timeout_ms": genai_types.Schema(type=genai_types.Type.INTEGER, description="Max wait in ms (default 10000)."),
            "network_idle": genai_types.Schema(type=genai_types.Type.BOOLEAN, description="If true, also wait for network to go idle."),
        },
        required=[],
    ),
)

_select_option_decl = genai_types.FunctionDeclaration(
    name="select_option",
    description="Select an option in a <select> element by value, label, or index.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector of the <select> element."),
            "value": genai_types.Schema(type=genai_types.Type.STRING, description="Option value or visible label to select."),
        },
        required=["selector", "value"],
    ),
)

_set_checked_decl = genai_types.FunctionDeclaration(
    name="set_checked",
    description="Check or uncheck a checkbox/radio input.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector of the checkbox/radio."),
            "checked": genai_types.Schema(type=genai_types.Type.BOOLEAN, description="True to check, false to uncheck."),
        },
        required=["selector", "checked"],
    ),
)

_read_elements_decl = genai_types.FunctionDeclaration(
    name="read_elements",
    description=(
        "Enumerate all elements matching a CSS selector and return their inner text, "
        "0-indexed. Use the returned index with click/fill's optional nth param to act "
        "on a specific one when the selector matches multiple elements."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector to enumerate."),
            "limit": genai_types.Schema(type=genai_types.Type.INTEGER, description="Max elements to return (default 50)."),
        },
        required=["selector"],
    ),
)

_get_attribute_decl = genai_types.FunctionDeclaration(
    name="get_attribute",
    description="Read one HTML attribute's value from an element.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector of the element."),
            "attribute": genai_types.Schema(type=genai_types.Type.STRING, description="Attribute name, e.g. 'href', 'value', 'disabled'."),
        },
        required=["selector", "attribute"],
    ),
)

_handle_dialog_decl = genai_types.FunctionDeclaration(
    name="handle_dialog",
    description=(
        "Pre-arm how the NEXT browser dialog (alert/confirm/prompt/beforeunload) will be "
        "handled. Call this BEFORE the action that triggers the dialog — dialogs auto-dismiss "
        "by default if unarmed."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "action": genai_types.Schema(type=genai_types.Type.STRING, description="accept or dismiss the next dialog.", enum=["accept", "dismiss"]),
            "prompt_text": genai_types.Schema(type=genai_types.Type.STRING, description="Text to enter if the dialog is a JS prompt() and action=accept."),
        },
        required=["action"],
    ),
)

_scroll_decl = genai_types.FunctionDeclaration(
    name="scroll",
    description="Scroll an element into view, or scroll the page by a pixel delta.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector to scroll into view (omit to scroll the viewport)."),
            "delta_y": genai_types.Schema(type=genai_types.Type.INTEGER, description="Vertical scroll amount in px (used when selector omitted; default 0)."),
            "delta_x": genai_types.Schema(type=genai_types.Type.INTEGER, description="Horizontal scroll amount in px (default 0)."),
        },
        required=[],
    ),
)

_navigate_history_decl = genai_types.FunctionDeclaration(
    name="navigate_history",
    description="Go back or forward in browser history.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "direction": genai_types.Schema(type=genai_types.Type.STRING, enum=["back", "forward"]),
        },
        required=["direction"],
    ),
)

_evaluate_js_decl = genai_types.FunctionDeclaration(
    name="evaluate_js",
    description=(
        "ESCAPE HATCH: run arbitrary JavaScript in the page context via page.evaluate() and "
        "return its JSON-serializable result. Powerful and unsandboxed relative to the other "
        "tools — prefer click/fill/read_page first; use this only when no other tool can "
        "express the needed interaction or read."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "script": genai_types.Schema(type=genai_types.Type.STRING, description="JS expression or function body to evaluate in page context."),
        },
        required=["script"],
    ),
)

_hover_decl = genai_types.FunctionDeclaration(
    name="hover",
    description="Hover the mouse over an element (reveals hover-triggered menus/tooltips).",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector to hover."),
        },
        required=["selector"],
    ),
)

_list_tabs_decl = genai_types.FunctionDeclaration(
    name="list_tabs",
    description="List all open tabs/pages with their 0-based index, title, and URL.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
)

_switch_tab_decl = genai_types.FunctionDeclaration(
    name="switch_tab",
    description="Switch the active tab/page by index (see list_tabs).",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "index": genai_types.Schema(type=genai_types.Type.INTEGER, description="0-based tab index from list_tabs."),
        },
        required=["index"],
    ),
)

_file_upload_decl = genai_types.FunctionDeclaration(
    name="file_upload",
    description="Upload a local file into a file input element.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "selector": genai_types.Schema(type=genai_types.Type.STRING, description="CSS selector of the file input."),
            "path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to the file to upload."),
        },
        required=["selector", "path"],
    ),
)

_network_requests_decl = genai_types.FunctionDeclaration(
    name="network_requests",
    description="Read recently observed network responses (url, status, method), most recent last.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "url_pattern": genai_types.Schema(type=genai_types.Type.STRING, description="Optional substring to filter URLs by."),
            "limit": genai_types.Schema(type=genai_types.Type.INTEGER, description="Max entries to return (default 30)."),
        },
        required=[],
    ),
)


class BrowserWorker(AgenticWorkerMixin, DomainWorker):
    """Playwright-backed browser worker using ReAct loop."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.gemini import GeminiProvider
            llm = GeminiProvider(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.5-flash"),
            )
        super().__init__(llm=llm)
        self._page: Any = None
        self._pages: list[Any] = []
        self._active_page_idx: int = 0
        self._dialog_policy: dict[str, Any] = {"action": "dismiss", "prompt_text": ""}
        self._last_dialog: dict[str, Any] | None = None
        self._network_log: list[dict[str, Any]] = []

    def _worker_system_prompt(self) -> str:
        return _BROWSER_AGENT_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            _navigate_decl,
            _click_decl,
            _fill_decl,
            _read_page_decl,
            _read_text_decl,
            _wait_for_decl,
            _select_option_decl,
            _set_checked_decl,
            _read_elements_decl,
            _get_attribute_decl,
            _handle_dialog_decl,
            _scroll_decl,
            _navigate_history_decl,
            _evaluate_js_decl,
            _hover_decl,
            _list_tabs_decl,
            _switch_tab_decl,
            _file_upload_decl,
            _network_requests_decl,
            _take_screenshot_decl,
            _finish_decl,
            _report_blocking_decl,
        ])]

    def _worker_environment_context(self, spec, evidence) -> str:
        page_url = evidence.get("page_url") or "about:blank"
        page_title = evidence.get("page_title") or ""
        lines = ["BROWSER STATE:"]
        lines.append(f"  Current URL: {page_url}")
        if page_title:
            lines.append(f"  Page title: {page_title!r}")
        if page_url == "about:blank":
            lines.append("  (Browser just started â€” no page loaded yet. Navigate to target URL first.)")
        return "\n".join(lines)

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:
        url = evidence.get("page_url") or "about:blank"
        title = evidence.get("page_title") or "unknown"
        status = evidence.get("page_http_status")
        status_str = str(status) if status is not None else "unknown"
        return f"current_url={url}\npage_title={title}\npage_status={status_str}"

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 300))
        evidence: dict[str, Any] = {
            "domain": "browser",
            "objective_id": spec.objective_id,
            "screenshot": None,
            "dom_snapshot": None,
            "page_title": None,
            "page_url": None,
            "page_http_status": None,
            "extracted_content": None,
            "trace_path": None,
            "error": None,
        }
        try:
            await asyncio.wait_for(
                self._execute_inner(spec, evidence),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise WorkerError(
                f"Browser timeout after {timeout_seconds}s for '{spec.objective_id}'"
            )
        except WorkerBlocker:
            raise
        validate_evidence(DomainType.BROWSER, evidence)
        return evidence

    async def _execute_inner(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WorkerError("playwright not installed") from exc

        trace_dir = Path(tempfile.mkdtemp(prefix="trinity-trace-"))
        trace_path = str(trace_dir / "trace.zip")

        async with async_playwright() as pw:
            # Software rendering bypasses VirtualBox SVGA3D D3D cold-start, same
            # fix already applied to the Qt app via QT_OPENGL=software in
            # tests/e2e/_gui_driver.py. Without --disable-gpu, Chromium's first
            # GPU init on a freshly-booted VM can block indefinitely.
            try:
                browser = await pw.chromium.launch(
                    headless=False,
                    args=["--no-sandbox", "--disable-gpu", "--use-gl=swiftshader"],
                )
            except Exception as exc:
                raise WorkerError(
                    "browser_launch_failed: Playwright Chromium could not start. "
                    "Run 'playwright install chromium' for this Python environment. "
                    f"Original error: {exc}"
                ) from exc
            context = await browser.new_context()
            try:
                await context.tracing.start(screenshots=True, snapshots=True)
                page = await context.new_page()
                self._register_page(page)
                # Registered AFTER creating the first page: context.on("page", ...)
                # fires for every page created on this context, including ones made
                # before the listener existed once the event loop catches up. If this
                # listener were installed first, new_page() above would fire it too,
                # double-registering the dialog/response handlers on the first page
                # (confirmed live: a real dialog crashed with "Dialog.accept: Cannot
                # accept dialog which is already handled!").
                context.on("page", lambda p: self._register_page(p))

                result = await self.run_loop(spec, evidence)
                evidence["worker_result_status"] = result.status
                evidence["worker_result_summary"] = result.summary

            except WorkerBlocker:
                raise
            except WorkerError:
                raise
            except Exception as exc:
                evidence["error"] = str(exc)
                try:
                    screenshot_bytes = await page.screenshot()
                    evidence["screenshot"] = base64.b64encode(screenshot_bytes).decode()
                    evidence["dom_snapshot"] = await page.content()
                    evidence["page_title"] = await page.title()
                    evidence["page_url"] = page.url
                except Exception:
                    pass
                raise WorkerError(
                    f"Browser execution failed for '{spec.objective_id}': {exc}"
                ) from exc
            finally:
                self._page = None
                self._pages = []
                self._active_page_idx = 0
                try:
                    await context.tracing.stop(path=trace_path)
                    evidence["trace_path"] = trace_path
                except Exception:
                    pass
                await context.close()
                await browser.close()

    def _register_page(self, page: Any) -> None:
        """Track a new page/tab (initial page or a popup/new-tab) and wire its handlers."""
        self._pages.append(page)
        if self._page is None:
            self._page = page
            self._active_page_idx = len(self._pages) - 1

        async def _on_dialog(dialog: Any) -> None:
            policy = self._dialog_policy
            self._last_dialog = {
                "type": dialog.type,
                "message": dialog.message,
                "action": policy["action"],
            }
            try:
                if policy["action"] == "accept":
                    if dialog.type == "prompt":
                        await dialog.accept(policy.get("prompt_text", ""))
                    else:
                        await dialog.accept()
                else:
                    await dialog.dismiss()
            finally:
                self._dialog_policy = {"action": "dismiss", "prompt_text": ""}

        def _on_response(response: Any) -> None:
            self._network_log.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
            })
            if len(self._network_log) > 200:
                del self._network_log[: len(self._network_log) - 200]

        page.on("dialog", lambda d: asyncio.ensure_future(_on_dialog(d)))
        page.on("response", _on_response)

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str | tuple[str, bytes] | _FinishSignal | _BlockerSignal:
        result = await self._dispatch_tool_inner(tool_name, args, evidence)
        # Surface any dialog the previous action triggered as part of THIS observation,
        # since Playwright's dialog handler runs asynchronously outside this call.
        if self._last_dialog is not None and isinstance(result, str):
            result = f"{result}\n[DIALOG] {self._last_dialog}"
            self._last_dialog = None
        return result

    async def _dispatch_tool_inner(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str | tuple[str, bytes] | _FinishSignal | _BlockerSignal:
        page = self._page
        if page is None:
            raise WorkerError("_dispatch_tool called with no active browser page")

        if tool_name == "navigate":
            url = args["url"]
            response = None
            for _nav_attempt in range(2):
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    await page.wait_for_selector("body", state="attached", timeout=10_000)
                except Exception as nav_err:
                    return (
                        f"NAVIGATION FAILED: {nav_err}. "
                        "The URL is unreachable (DNS failure, connection refused, or timeout). "
                        "Call finish with status=failure."
                    )
                if response is not None and response.status >= 500 and _nav_attempt == 0:
                    import asyncio as _asyncio
                    await _asyncio.sleep(5)
                    continue
                break
            evidence["page_url"] = page.url
            evidence["page_http_status"] = response.status if response is not None else None
            status_info = f" (HTTP {response.status})" if response is not None else ""
            return f"Navigated to {url}{status_info}"

        elif tool_name == "click":
            selector = args["selector"]
            nth = int(args.get("nth", 0))
            await page.locator(selector).nth(nth).click(timeout=10_000)
            return f"Clicked {selector}[{nth}]"

        elif tool_name == "fill":
            selector = args["selector"]
            value = args["value"]
            nth = int(args.get("nth", 0))
            await page.locator(selector).nth(nth).fill(value, timeout=10_000)
            return f"Filled {selector}[{nth}] with {value!r}"

        elif tool_name == "read_page":
            dom_text = await self._visible_page_text(page)
            self._record_extracted_content(evidence, dom_text, source="read_page")
            await self._capture_read_evidence(page, evidence, "read_page", dom_text)
            return f"title={evidence['page_title']!r} url={evidence['page_url']}\ntext={dom_text}"

        elif tool_name == "read_text":
            selector = args["selector"]
            text = (await page.locator(selector).first.inner_text(timeout=10_000)).strip()
            self._record_extracted_content(evidence, text, source=f"read_text:{selector}")
            await self._capture_read_evidence(page, evidence, "read_text", text, selector=selector)
            evidence.setdefault("extracted_text", {})[selector] = text
            evidence.setdefault("action_log", []).append(f"read_text: {selector}")
            return text

        elif tool_name == "wait_for":
            selector = args.get("selector")
            state = args.get("state", "visible")
            timeout_ms = int(args.get("timeout_ms", 10_000))
            try:
                if selector:
                    await page.wait_for_selector(selector, state=state, timeout=timeout_ms)
                if args.get("network_idle"):
                    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
                return f"wait_for satisfied (selector={selector!r}, state={state}, network_idle={bool(args.get('network_idle'))})"
            except Exception as exc:
                return f"wait_for TIMED OUT: {exc}"

        elif tool_name == "select_option":
            selector = args["selector"]
            value = args["value"]
            await page.locator(selector).select_option(value, timeout=10_000)
            return f"Selected {value!r} in {selector}"

        elif tool_name == "set_checked":
            selector = args["selector"]
            checked = bool(args["checked"])
            await page.locator(selector).set_checked(checked, timeout=10_000)
            return f"Set {selector} checked={checked}"

        elif tool_name == "read_elements":
            selector = args["selector"]
            limit = int(args.get("limit", 50))
            locator = page.locator(selector)
            texts = await locator.all_inner_texts()
            texts = texts[:limit]
            listing = "\n".join(f"[{i}] {t.strip()[:200]}" for i, t in enumerate(texts))
            self._record_extracted_content(evidence, listing or "(no matches)", source=f"read_elements:{selector}")
            await self._capture_read_evidence(page, evidence, "read_elements", listing, selector=selector)
            return f"{len(texts)} element(s) matched {selector}:\n{listing}"

        elif tool_name == "get_attribute":
            selector = args["selector"]
            attribute = args["attribute"]
            value = await page.locator(selector).first.get_attribute(attribute, timeout=10_000)
            text = f"{attribute}={value!r}"
            self._record_extracted_content(evidence, text, source=f"get_attribute:{selector}.{attribute}")
            await self._capture_read_evidence(page, evidence, "get_attribute", text, selector=selector)
            return text

        elif tool_name == "handle_dialog":
            self._dialog_policy = {"action": args["action"], "prompt_text": args.get("prompt_text", "")}
            return f"Armed next dialog: action={args['action']!r}"

        elif tool_name == "scroll":
            selector = args.get("selector")
            if selector:
                await page.locator(selector).scroll_into_view_if_needed(timeout=10_000)
                return f"Scrolled {selector} into view"
            delta_x = int(args.get("delta_x", 0))
            delta_y = int(args.get("delta_y", 0))
            await page.mouse.wheel(delta_x, delta_y)
            return f"Scrolled viewport by dx={delta_x}, dy={delta_y}"

        elif tool_name == "navigate_history":
            direction = args["direction"]
            response = (
                await page.go_back(timeout=10_000) if direction == "back"
                else await page.go_forward(timeout=10_000)
            )
            evidence["page_url"] = page.url
            evidence["page_http_status"] = response.status if response is not None else None
            if response is not None:
                return f"Navigated {direction} to {page.url}"
            return f"No page to go {direction} to; url unchanged ({page.url})"

        elif tool_name == "evaluate_js":
            script = args["script"]
            try:
                js_result = await page.evaluate(script)
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"evaluate_js FAILED: {script!r} -> {exc}")
                return f"evaluate_js FAILED: {exc}"
            evidence.setdefault("action_log", []).append(f"evaluate_js: {script!r} -> {js_result!r}")
            return f"evaluate_js result: {js_result!r}"

        elif tool_name == "hover":
            selector = args["selector"]
            await page.locator(selector).hover(timeout=10_000)
            return f"Hovered {selector}"

        elif tool_name == "list_tabs":
            rows = []
            for i, p in enumerate(self._pages):
                try:
                    title = await p.title()
                except Exception:
                    title = ""
                marker = " (active)" if i == self._active_page_idx else ""
                rows.append(f"[{i}] title={title!r} url={p.url!r}{marker}")
            return f"{len(self._pages)} tab(s):\n" + "\n".join(rows)

        elif tool_name == "switch_tab":
            index = int(args["index"])
            if index < 0 or index >= len(self._pages):
                return f"switch_tab failed: index {index} out of range (0..{len(self._pages) - 1})"
            self._active_page_idx = index
            self._page = self._pages[index]
            return f"Switched to tab {index} ({self._page.url!r})"

        elif tool_name == "file_upload":
            selector = args["selector"]
            path = args["path"]
            workspace = evidence.get("workspace")
            resolved = Path(path).resolve()
            if workspace and not str(resolved).startswith(str(Path(workspace).resolve())):
                return f"file_upload REFUSED: {path} is outside the workspace directory."
            if not resolved.is_file():
                return f"file_upload failed: {path} does not exist."
            try:
                await page.locator(selector).set_input_files(str(resolved), timeout=10_000)
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"file_upload failed: {selector}: {exc}")
                return f"file_upload failed: {exc}"
            evidence.setdefault("action_log", []).append(f"file_upload: {selector} <- {resolved}")
            return f"Uploaded {resolved} into {selector}"

        elif tool_name == "network_requests":
            url_pattern = args.get("url_pattern")
            limit = int(args.get("limit", 30))
            entries = self._network_log
            if url_pattern:
                entries = [e for e in entries if url_pattern in e["url"]]
            entries = entries[-limit:]
            listing = "\n".join(f"{e['method']} {e['status']} {e['url']}" for e in entries)
            return f"{len(entries)} network response(s):\n{listing}" if entries else "No network responses recorded yet."

        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    @staticmethod
    async def _visible_page_text(page: Any) -> str:
        """Return meaningful visible content rather than regex-stripped document markup."""
        try:
            text = await page.locator("main").first.inner_text(timeout=5_000)
        except Exception:
            text = await page.locator("body").first.inner_text(timeout=5_000)
        return re.sub(r"\s+", " ", text).strip()[:4_000]

    @staticmethod
    def _record_extracted_content(evidence: dict[str, Any], text: str, *, source: str) -> None:
        """Store every browser read in the one completion/review contract."""
        content = text.strip()
        if not content:
            raise WorkerError(f"{source} returned empty visible text")
        evidence["extracted_content"] = content
        # Keep legacy evidence consumers working while they migrate to the
        # canonical field above.
        evidence["visible_text"] = content

    @staticmethod
    async def _capture_read_evidence(
        page: Any,
        evidence: dict[str, Any],
        kind: str,
        text: str,
        *,
        selector: str | None = None,
    ) -> None:
        """Capture fresh, observable state for a successful browser read."""
        evidence["page_title"] = await page.title()
        evidence["page_url"] = page.url
        evidence["dom_snapshot"] = await page.content()
        screenshot_bytes = await page.screenshot()
        evidence["screenshot"] = base64.b64encode(screenshot_bytes).decode()
        result: dict[str, Any] = {
            "type": kind,
            "text": text,
            "text_length": len(text),
            "title": evidence["page_title"],
            "url": evidence["page_url"],
            "http_status": evidence.get("page_http_status"),
        }
        if selector:
            result["selector"] = selector
        evidence.setdefault("action_results", []).append(result)
