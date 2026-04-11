from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.active_reviewer import ActiveReviewer, ReviewStatus


def test_parse_review_accepts_uppercase_status_and_scalar_fields() -> None:
    reviewer = ActiveReviewer(llm_provider=None)

    result = reviewer._parse_review(  # noqa: SLF001
        {
            "status": "FAILED",
            "assessment": "Not done yet",
            "missing": "dashboard",
            "next_steps": "wait and retry",
            "hints": None,
            "alternative_strategies": "reload page",
            "confidence": "0.9",
        }
    )

    assert result.status == ReviewStatus.FAILED
    assert result.missing == ["dashboard"]
    assert result.next_steps == ["wait and retry"]
    assert result.alternative_strategies == ["reload page"]
    assert result.confidence == 0.9


def test_parse_review_falls_back_to_continue_for_unknown_status() -> None:
    reviewer = ActiveReviewer(llm_provider=None)

    result = reviewer._parse_review({"status": "maybe", "assessment": "unclear"})  # noqa: SLF001

    assert result.status == ReviewStatus.CONTINUE
