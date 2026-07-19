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
    _finish_decl,
    _make_tool,
    _report_blocking_decl,
    _take_screenshot_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence
from trinity_pilot.workers.worker_result import WorkerResult
from trinity_pilot.workers.write_verification import verify_and_write_file


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

[ACTION] navigate: Navigate to a URL.
[ACTION] click: Click a CSS selector on the current page.
[ACTION] fill: Fill an input field on the current page.
[ACTION] finish: Signal that the objective is complete or definitively failed.
[ACTION] report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

RULES:
- Always navigate to a URL first before interacting with elements.
- After each ACTION tool call, read its result before proceeding. If a tool failed or
  produced unexpected state, adapt â€” do not blindly continue to the next planned step.
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

    def _worker_system_prompt(self) -> str:
        return _BROWSER_AGENT_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            _navigate_decl,
            _click_decl,
            _fill_decl,
            _read_page_decl,
            _read_text_decl,
            _take_screenshot_decl,
            _finish_decl,
            _report_blocking_decl,
        ])]

    def _worker_environment_context(self, spec, evidence) -> str:  # type: ignore[override]
        page_url = evidence.get("page_url") or "about:blank"
        page_title = evidence.get("page_title") or ""
        lines = ["BROWSER STATE:"]
        lines.append(f"  Current URL: {page_url}")
        if page_title:
            lines.append(f"  Page title: {page_title!r}")
        if page_url == "about:blank":
            lines.append("  (Browser just started â€” no page loaded yet. Navigate to target URL first.)")
        return "\n".join(lines)

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:  # type: ignore[override]
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
                self._page = page

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
                try:
                    await context.tracing.stop(path=trace_path)
                    evidence["trace_path"] = trace_path
                except Exception:
                    pass
                await context.close()
                await browser.close()

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str:
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
            await page.click(selector, timeout=10_000)
            return f"Clicked {selector}"

        elif tool_name == "fill":
            selector = args["selector"]
            value = args["value"]
            await page.fill(selector, value, timeout=10_000)
            return f"Filled {selector} with {value!r}"

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
