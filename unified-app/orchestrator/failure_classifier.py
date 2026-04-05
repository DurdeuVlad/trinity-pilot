"""Classify automation failures to drive retry policy decisions."""

from __future__ import annotations

from enum import Enum


class FailureKind(Enum):
    """High-level failure kinds used by the orchestration retry policy."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    AMBIGUOUS = "ambiguous"


_TRANSIENT_MARKERS = (
    "timeout",
    "rate limit",
    "api error",
    "connection",
    "temporarily",
    "retry",
    "503",
    "429",
)

_PERMANENT_MARKERS = (
    "not found",
    "does not exist",
    "cannot",
    "not installed",
    "unavailable",
    "infeasible",
    "unable to locate",
)


def classify(error_text: str) -> FailureKind:
    """Classify free-form failure text into transient/permanent/ambiguous."""

    normalized = (error_text or "").strip().lower()
    if any(marker in normalized for marker in _TRANSIENT_MARKERS):
        return FailureKind.TRANSIENT
    if any(marker in normalized for marker in _PERMANENT_MARKERS):
        return FailureKind.PERMANENT
    return FailureKind.AMBIGUOUS
