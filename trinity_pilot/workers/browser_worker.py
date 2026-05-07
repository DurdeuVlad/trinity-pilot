from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError

_PROFILE_DIR = Path.home() / ".trinity-pilot" / "browser-profile"


class BrowserWorker(DomainWorker):
    """Playwright-backed browser worker. One context per attempt, closed in finally."""

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WorkerError("playwright not installed") from exc

        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
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

        return evidence

    async def _run_objective(
        self,
        page: Any,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
    ) -> None:
        import base64

        # Parse goal for structured actions (simple keyword dispatch)
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
    def _extract_url(text: str) -> str | None:
        import re
        match = re.search(r"https?://[^\s\"']+", text)
        return match.group(0) if match else None
