from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_PROFILE_DIR = Path.home() / ".trinity-pilot" / "browser-profile"

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


class BrowserWorker(DomainWorker):
    """Playwright-backed browser worker. One context per attempt, closed in finally."""

    def __init__(self) -> None:
        super().__init__()

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
        validate_evidence(DomainType.BROWSER, evidence)
        return evidence

    async def _execute_inner(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WorkerError("playwright not installed") from exc

        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        trace_dir = Path(tempfile.mkdtemp(prefix="trinity-trace-"))
        trace_path = str(trace_dir / "trace.zip")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_PROFILE_DIR),
                headless=False,
                args=["--no-sandbox"],
            )
            try:
                await browser.tracing.start(screenshots=True, snapshots=True)
                page = browser.pages[0] if browser.pages else await browser.new_page()

                await self._run_objective(page, spec, evidence)
                # After navigation, synthesize file writes only when goal requires saving data
                if any(kw in spec.goal.lower() for kw in ("save", "write", "download", "export", "store")):
                    await self._synthesize_file_writes(spec, evidence)

            except WorkerError:
                raise
            except Exception as exc:
                evidence["error"] = str(exc)
                # Capture failure evidence
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
                try:
                    await browser.tracing.stop(path=trace_path)
                    evidence["trace_path"] = trace_path
                except Exception:
                    pass
                await browser.close()

    async def _run_objective(
        self,
        page: Any,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
    ) -> None:
        # Try structured JSON action list first: {"actions": [...]}
        actions_executed = False
        json_match = re.search(r'\{.*"actions"\s*:.*\}', spec.goal, re.DOTALL)
        if json_match:
            try:
                action_data = json.loads(json_match.group(0))
                actions = action_data.get("actions", [])
                for action in actions:
                    await self._dispatch_action(page, action)
                actions_executed = True
            except Exception:
                pass  # fall through to keyword dispatch

        # Keyword dispatch fallback
        if not actions_executed:
            goal_lower = spec.goal.lower()
            if "navigate" in goal_lower or "open" in goal_lower or "go to" in goal_lower:
                url = self._extract_url(spec.goal)
                if url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Collect evidence
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
            pass  # evidence collected separately via dom_snapshot

    @staticmethod
    def _extract_url(text: str) -> str | None:
        match = re.search(r"https?://[^\s\"']+", text)
        return match.group(0) if match else None

    async def _synthesize_file_writes(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> None:
        """After navigation, ask LLM to produce write_file actions from captured evidence."""
        from trinity_pilot.llm.base import LLMMessage
        from trinity_pilot.llm.gemini import GeminiProvider

        page_title = evidence.get("page_title") or ""
        page_url = evidence.get("page_url") or ""
        dom_raw = evidence.get("dom_snapshot") or ""
        # Strip HTML tags for a readable text preview
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
