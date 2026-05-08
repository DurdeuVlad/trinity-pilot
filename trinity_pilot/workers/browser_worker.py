from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

_PROFILE_DIR = Path.home() / ".trinity-pilot" / "browser-profile"


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
        import base64
        import json as _json
        import re

        # Try structured JSON action list first: {"actions": [...]}
        actions_executed = False
        json_match = re.search(r'\{.*"actions"\s*:.*\}', spec.goal, re.DOTALL)
        if json_match:
            try:
                action_data = _json.loads(json_match.group(0))
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
        import re
        match = re.search(r"https?://[^\s\"']+", text)
        return match.group(0) if match else None
