"""Tests for recovery_hint field in ReviewResult and reviewer parsing."""
from __future__ import annotations

import json

import pytest

from trinity_pilot.core.types import DomainType, FailureReason, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer


def _spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-rh",
        goal="Navigate to example.com",
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["page title is 'Example Domain'"],
        evidence_bundle=["screenshot"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


class StubProvider(LLMProvider):
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def complete(self, messages, system="") -> LLMResponse:
        return LLMResponse(content=self._reply)

    async def complete_with_tools(self, messages, tools, system="") -> LLMResponse:
        return LLMResponse(content=self._reply)


class TestReviewerRecoveryHint:
    async def test_recovery_hint_populated_on_failure(self):
        payload = json.dumps({
            "passed": False,
            "failure_reason": "wrong_output",
            "notes": "title mismatch",
            "recovery_hint": "wait longer for page load",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_spec(), {})
        assert result.recovery_hint == "wait longer for page load"
        assert result.failure_reason == FailureReason.WRONG_OUTPUT

    async def test_recovery_hint_empty_on_pass(self):
        payload = json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "all good",
            "recovery_hint": "",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_spec(), {"screenshot": "data"})
        assert result.passed is True
        assert result.recovery_hint == ""

    async def test_recovery_hint_defaults_to_empty_if_missing(self):
        payload = json.dumps({
            "passed": False,
            "failure_reason": "missing_artifact",
            "notes": "no screenshot",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_spec(), {})
        assert result.recovery_hint == ""
