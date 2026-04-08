"""Desktop objective reviewer."""

from __future__ import annotations

from typing import Any

from ..adapters.desktop import DesktopAdapter
from .review_types import ReviewResult


class DesktopReviewer:
    def __init__(self, adapter: DesktopAdapter) -> None:
        self.adapter = adapter

    async def review(
        self,
        objective: str,
        definition_of_done: str,
        execution_log: list[dict[str, Any]],
    ) -> ReviewResult:
        tool_entries = [entry for entry in execution_log if entry.get("role") == "tool"]
        if any(entry.get("status") == "error" for entry in tool_entries):
            return ReviewResult(False, "Desktop execution still has tool failures.")

        objective_l = objective.lower()
        if "open" in objective_l and "open" not in str(tool_entries).lower():
            return ReviewResult(False, "Objective expects an app launch but launch evidence was not found.")

        if "window" in objective_l and "window" not in str(tool_entries).lower():
            return ReviewResult(False, "Objective expects a visible window but no window evidence was found.")

        if definition_of_done and definition_of_done.lower() not in str(tool_entries).lower() and not tool_entries:
            return ReviewResult(False, "Definition of done has no desktop evidence yet.")

        return ReviewResult(True, "Desktop objective validated successfully.")
