"""CLI objective reviewer."""

from __future__ import annotations

from typing import Any

from ..adapters.cli import CLIAdapter
from .review_types import ReviewResult


class CLIReviewer:
    def __init__(self, adapter: CLIAdapter) -> None:
        self.adapter = adapter

    async def review(
        self,
        objective: str,
        definition_of_done: str,
        execution_log: list[dict[str, Any]],
    ) -> ReviewResult:
        tool_entries = [entry for entry in execution_log if entry.get("role") == "tool"]
        if any(entry.get("status") == "error" for entry in tool_entries):
            return ReviewResult(False, "CLI execution contains errors and is not complete.")

        aggregate = " ".join(str(entry.get("content", "")) for entry in tool_entries).lower()
        if "output" in objective.lower() and aggregate.strip() == "":
            return ReviewResult(False, "Objective requires command output but output evidence is empty.")

        if definition_of_done and definition_of_done.lower() not in aggregate and not tool_entries:
            return ReviewResult(False, "Definition of done has not been satisfied yet.")

        return ReviewResult(True, "CLI objective validated successfully.")
