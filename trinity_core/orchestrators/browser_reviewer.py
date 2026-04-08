"""Browser objective reviewer."""

from __future__ import annotations

from typing import Any

from ..adapters.browser import BrowserAdapter
from .review_types import ReviewResult


class BrowserReviewer:
    def __init__(self, adapter: BrowserAdapter) -> None:
        self.adapter = adapter

    async def review(
        self,
        objective: str,
        definition_of_done: str,
        execution_log: list[dict[str, Any]],
    ) -> ReviewResult:
        objective_l = objective.lower()
        tool_entries = [entry for entry in execution_log if entry.get("role") == "tool"]
        errors = [entry for entry in tool_entries if entry.get("status") == "error"]
        if errors:
            return ReviewResult(False, "Tool execution still contains errors. Resolve failures and retry.")

        called_text = " ".join(str(entry.get("content", "")) for entry in tool_entries).lower()
        if "extract" in objective_l and "extract" not in called_text:
            return ReviewResult(False, "Objective requires extraction, but extraction evidence is missing.")

        if "navigate" in objective_l:
            current_url = await self.adapter.get_current_url()
            if not current_url:
                return ReviewResult(False, "Navigation objective is missing a final URL confirmation.")

        if "search" in objective_l and "result" not in called_text:
            return ReviewResult(False, "Search objective lacks evidence of results on page.")

        if definition_of_done and definition_of_done.lower() not in called_text and not tool_entries:
            return ReviewResult(False, "Definition of done has no matching completion evidence.")

        return ReviewResult(True, "Objective validated successfully.")
