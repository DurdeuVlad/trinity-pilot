"""Common review result model for runtime reviewers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReviewResult:
    approved: bool
    feedback: str
