from __future__ import annotations

import asyncio
import base64
import json
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
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_BROWSER_SYNTH_SYSTEM = """\
You are a browser automation agent that has just navigated to a web page.
Based on the original goal and the captured page data, output ONLY a JSON array
of write_file actions to save the required information to disk.

Each action: {"action":"write_file","path":"<absolute-path>","content":"<text>"}

RULES:
- Extract the data the goal asks for from PAGE TITLE and PAGE HTML.
- Use the exact file path specified in the goal.
- For JSON pages (like httpbin), parse the visible text to find the requested field.
- The content should contain exactly what the goal asks to be saved — no extra commentary.
- Return ONLY the JSON array. No markdown fences, no prose.
"""

_BROWSER_AGENT_SYSTEM = """\
You are a browser automation agent using Playwright on a live browser.
Use the available tools to accomplish the goal step by step.

Available tools:
- navigate: Navigate to a URL.
- click: Click a CSS selector on the current page.
- fill: Fill an input field on the current page.
- read_page: Read the current page title, URL, and DOM text preview.
- finish: Signal that the objective is complete or definitively failed.
- report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

RULES:
- Always navigate to a URL first before interacting with elements.
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


class BrowserWorker(AgenticWorkerMixin, DomainWorker):
    """Playwright-backed browser worker using ReAct loop."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.gemini import GeminiProvider
            llm = GeminiProvider(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
            )
        super().__init__(llm=llm)
        self._page: Any = None

    def _worker_system_prompt(self) -> str:
        return _BROWSER_AGENT_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([_navigate_decl, _click_decl, _fill_decl, _read_page_decl, _finish_decl, _report_blocking_decl])]

    def _worker_environment_context(self, spec, evidence) -> str:  # type: ignore[override]
        page_url = evidence.get("page_url") or "about:blank"
        page_title = evidence.get("page_title") or ""
        lines = ["BROWSER STATE:"]
        lines.append(f"  Current URL: {page_url}")
        if page_title:
            lines.append(f"  Page title: {page_title!r}")
        if page_url == "about:blank":
            lines.append("  (Browser just started — no page loaded yet. Navigate to target URL first.)")
        return "\n".join(lines)

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 60))
        evidence: dict[str, Any] = {
            "domain": "browser",
            "objective_id": spec.objective_id,
            "screenshot": None,
            "dom_snapshot": None,
            "page_title": None,
            "page_url": None,
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
            browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])
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
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            evidence["page_url"] = page.url
            return f"Navigated to {url}"

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
            title = await page.title()
            url = page.url
            dom_raw = await page.content()
            dom_text = re.sub(r"<[^>]+>", " ", dom_raw)
            dom_text = re.sub(r"\s+", " ", dom_text).strip()[:2000]
            evidence["page_title"] = title
            evidence["page_url"] = url
            evidence["dom_snapshot"] = dom_raw
            screenshot_bytes = await page.screenshot()
            evidence["screenshot"] = base64.b64encode(screenshot_bytes).decode()
            return f"title={title!r} url={url}\ntext={dom_text}"

        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    # ------------------------------------------------------------------
    # Backward-compatible helpers
    # ------------------------------------------------------------------

    async def _run_objective(
        self,
        page: Any,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
    ) -> None:
        actions_executed = False

        metadata_actions = spec.metadata.get("actions")
        if metadata_actions and isinstance(metadata_actions, list) and len(metadata_actions) > 0:
            for action in metadata_actions:
                await self._dispatch_action(page, action)
            actions_executed = True

        if not actions_executed:
            json_match = re.search(r'\{.*"actions"\s*:.*\}', spec.goal, re.DOTALL)
            if json_match:
                try:
                    action_data = json.loads(json_match.group(0))
                    actions = action_data.get("actions", [])
                    for action in actions:
                        await self._dispatch_action(page, action)
                    actions_executed = True
                except Exception:
                    pass

        if not actions_executed:
            goal_lower = spec.goal.lower()
            if "navigate" in goal_lower or "open" in goal_lower or "go to" in goal_lower:
                url = self._extract_url(spec.goal)
                if url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        screenshot_bytes = await page.screenshot()
        evidence["screenshot"] = base64.b64encode(screenshot_bytes).decode()
        evidence["dom_snapshot"] = await page.content()
        evidence["page_title"] = await page.title()
        evidence["page_url"] = page.url

    @staticmethod
    async def _dispatch_action(page: Any, action: dict[str, Any]) -> None:
        kind = action.get("type", "")
        if kind == "navigate":
            await page.goto(action["url"], wait_until="domcontentloaded", timeout=30_000)
        elif kind == "click":
            await page.click(action["selector"], timeout=10_000)
        elif kind == "fill":
            await page.fill(action["selector"], action["value"], timeout=10_000)
        elif kind == "wait_for":
            await page.wait_for_selector(action["selector"], timeout=10_000)
        elif kind == "read_text":
            pass

    @staticmethod
    def _extract_url(text: str) -> str | None:
        match = re.search(r"https?://[^\s\"']+", text)
        return match.group(0) if match else None

    async def _synthesize_file_writes(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> None:
        from trinity_pilot.llm.base import LLMMessage
        from trinity_pilot.llm.gemini import GeminiProvider

        page_title = evidence.get("page_title") or ""
        page_url = evidence.get("page_url") or ""
        dom_raw = evidence.get("dom_snapshot") or ""
        dom_text = re.sub(r"<[^>]+>", " ", dom_raw)
        dom_text = re.sub(r"\s+", " ", dom_text).strip()[:4000]

        provider = GeminiProvider(
            api_key=os.environ["GEMINI_API_KEY"],
            model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
        )
        user_msg = (
            f"GOAL: {spec.goal}\n\n"
            f"PAGE TITLE: {page_title}\n"
            f"PAGE URL: {page_url}\n"
            f"PAGE TEXT (first 4000 chars):\n{dom_text}\n\n"
            "Generate the write_file JSON array now."
        )
        response = await provider.complete(
            [LLMMessage(role="user", content=user_msg)],
            system=_BROWSER_SYNTH_SYSTEM,
        )
        raw = response.content.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*(?:```|$)", raw)
        if match:
            raw = match.group(1).strip()
        try:
            actions = json.loads(raw)
        except Exception as exc:
            raise WorkerError(f"LLM produced invalid JSON for file writes: {exc}") from exc

        for step in actions:
            if step.get("action") == "write_file":
                path = step["path"]
                content = step["content"]
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(content, encoding="utf-8")
                evidence.setdefault("action_log", []).append(
                    f"Wrote file: {path} ({len(content)} chars)"
                )
