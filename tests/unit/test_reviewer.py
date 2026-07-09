"""Reviewer unit tests. No live API calls — stub LLMProvider."""
from __future__ import annotations

import json

import pytest

from trinity_pilot.core.types import (
    DomainType,
    FailureReason,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer, ReviewError


def _make_spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-1",
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
        self.complete_calls = 0

    async def complete(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        self.complete_calls += 1
        return LLMResponse(content=self._reply)

    async def complete_with_tools(self, messages, tools, system="") -> LLMResponse:
        return LLMResponse(content=self._reply)


class TestObjectiveReviewer:
    async def test_passed_review(self):
        payload = json.dumps({"passed": True, "failure_reason": None, "notes": "all good"})
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {"screenshot": "data"})
        assert result.passed is True
        assert result.failure_reason is None
        assert result.notes == "all good"

    async def test_failed_with_missing_artifact(self):
        payload = json.dumps({
            "passed": False,
            "failure_reason": "missing_artifact",
            "notes": "screenshot not found",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {})
        assert result.passed is False
        assert result.failure_reason == FailureReason.MISSING_ARTIFACT

    async def test_failed_with_wrong_output(self):
        payload = json.dumps({
            "passed": False,
            "failure_reason": "wrong_output",
            "notes": "wrong page title",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {"screenshot": "data"})
        assert result.failure_reason == FailureReason.WRONG_OUTPUT

    async def test_unrecognised_failure_reason_defaults_to_failed_assertion(self):
        payload = json.dumps({
            "passed": False,
            "failure_reason": "some_unknown_reason",
            "notes": "something went wrong",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {})
        assert result.failure_reason == FailureReason.FAILED_ASSERTION

    async def test_malformed_json_raises_review_error(self):
        reviewer = ObjectiveReviewer(StubProvider("not json {{{"))
        with pytest.raises(ReviewError, match="invalid JSON"):
            await reviewer.review(_make_spec(), {})

    async def test_strips_markdown_fence(self):
        payload = "```json\n" + json.dumps({"passed": True, "failure_reason": None, "notes": ""}) + "\n```"
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {})
        assert result.passed is True

    async def test_strips_trailing_commas_from_llm_json(self):
        payload = """
        ```json
        {
          "passed": true,
          "failure_reason": null,
          "notes": "ok",
        }
        ```
        """
        reviewer = ObjectiveReviewer(StubProvider(payload))

        result = await reviewer.review(_make_spec(), {})

        assert result.passed is True

    async def test_recovery_hint_populated_on_failure(self):
        payload = json.dumps({
            "passed": False,
            "failure_reason": "wrong_output",
            "notes": "title mismatch",
            "recovery_hint": "scroll down before taking screenshot",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {"screenshot": "data"})
        assert result.recovery_hint == "scroll down before taking screenshot"

    async def test_recovery_hint_empty_on_pass(self):
        payload = json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "all good",
            "recovery_hint": "",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {"screenshot": "data"})
        assert result.recovery_hint == ""

    async def test_recovery_hint_defaults_to_empty_string_when_missing(self):
        payload = json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "ok",
        })
        reviewer = ObjectiveReviewer(StubProvider(payload))
        result = await reviewer.review(_make_spec(), {})
        assert result.recovery_hint == ""

    async def test_file_only_delivery_floor_bypasses_llm_even_if_llm_would_pass(self):
        provider = StubProvider(json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "llm would pass",
        }))
        reviewer = ObjectiveReviewer(provider)

        result = await reviewer.review(_make_spec(), {
            "visible_text_probe": {
                "passed": False,
                "visible_text_match": False,
                "screenshot_text_match": False,
                "file_only_delivery": True,
                "evidence_source": "file",
                "reason": "File-only delivery is insufficient for desktop typing proof",
            },
        })

        assert result.passed is False
        assert result.failure_reason == FailureReason.MISSING_ARTIFACT
        assert "file-only delivery" in result.notes
        assert provider.complete_calls == 0

    async def test_write_file_floor_short_circuits_before_checklist_is_evaluated(self):
        from trinity_pilot.core.types import ChecklistItem

        provider = StubProvider(json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "checklist item would pass, never called",
        }))
        reviewer = ObjectiveReviewer(provider)
        spec = _make_spec()
        spec.verification_checklist = (
            ChecklistItem(instruction="stdout looks fine", sensors=("stdout",)),
        )

        result = await reviewer.review(spec, {
            "write_file_failures": [{"path": "C:/out.txt", "error": "disk full"}],
            "stdout": "fine",
        })

        assert result.passed is False
        assert result.failure_reason == FailureReason.MISSING_ARTIFACT
        assert provider.complete_calls == 0  # checklist never reached, floor wins

    async def test_checklist_evaluated_when_no_hard_floor_fires(self):
        from trinity_pilot.core.types import ChecklistItem

        provider = StubProvider(json.dumps({"passed": True, "notes": "matches"}))
        reviewer = ObjectiveReviewer(provider)
        spec = _make_spec()
        spec.verification_checklist = (
            ChecklistItem(instruction="stdout looks fine", sensors=("stdout",)),
        )

        result = await reviewer.review(spec, {"stdout": "fine"})

        assert result.passed is True
        assert provider.complete_calls == 1

    async def test_visible_text_floor_absent_falls_through_to_llm(self):
        provider = StubProvider(json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "llm pass",
        }))
        reviewer = ObjectiveReviewer(provider)

        result = await reviewer.review(_make_spec(), {})

        assert result.passed is True
        assert provider.complete_calls == 1

    async def test_visible_text_floor_does_not_trigger_when_probe_passed(self):
        provider = StubProvider(json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "llm pass",
        }))
        reviewer = ObjectiveReviewer(provider)

        result = await reviewer.review(_make_spec(), {
            "visible_text_probe": {
                "passed": True,
                "visible_text_match": True,
                "screenshot_text_match": False,
                "file_only_delivery": False,
                "evidence_source": "uia_text",
                "reason": "Expected text is visible in UIA text",
            },
        })

        assert result.passed is True
        assert provider.complete_calls == 1

    async def test_visible_text_floor_does_not_trigger_for_non_file_only_failure(self):
        provider = StubProvider(json.dumps({
            "passed": False,
            "failure_reason": "wrong_output",
            "notes": "llm failure",
        }))
        reviewer = ObjectiveReviewer(provider)

        result = await reviewer.review(_make_spec(), {
            "visible_text_probe": {
                "passed": False,
                "visible_text_match": False,
                "screenshot_text_match": False,
                "file_only_delivery": False,
                "evidence_source": "none",
                "reason": "No visible UI or screenshot-backed text evidence matched",
            },
        })

        assert result.passed is False
        assert result.failure_reason == FailureReason.WRONG_OUTPUT
        assert provider.complete_calls == 1

    async def test_floor_shadow_mode_defaults_off(self):
        provider = StubProvider(json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "llm would pass",
        }))
        reviewer = ObjectiveReviewer(provider)

        await reviewer.review(_make_spec(), {
            "visible_text_probe": {
                "passed": False,
                "file_only_delivery": True,
            },
        })

        assert provider.complete_calls == 0
        assert reviewer.shadow_floor_trigger_count == 0
        assert reviewer.floor_override_count == 0
        assert reviewer.floor_override_rate == 0.0

    async def test_floor_shadow_mode_counts_llm_pass_as_override(self):
        provider = StubProvider(json.dumps({
            "passed": True,
            "failure_reason": None,
            "notes": "llm would pass",
        }))
        reviewer = ObjectiveReviewer(provider)

        result = await reviewer.review(
            _make_spec(),
            {
                "visible_text_probe": {
                    "passed": False,
                    "file_only_delivery": True,
                },
            },
            shadow_llm_on_floor_trigger=True,
        )

        assert result.passed is False
        assert provider.complete_calls == 1
        assert reviewer.shadow_floor_trigger_count == 1
        assert reviewer.floor_override_count == 1
        assert reviewer.floor_override_rate == 1.0

    async def test_floor_shadow_mode_does_not_count_llm_failure_as_override(self):
        provider = StubProvider(json.dumps({
            "passed": False,
            "failure_reason": "missing_artifact",
            "notes": "llm also fails",
        }))
        reviewer = ObjectiveReviewer(provider)

        result = await reviewer.review(
            _make_spec(),
            {
                "visible_text_probe": {
                    "passed": False,
                    "file_only_delivery": True,
                },
            },
            shadow_llm_on_floor_trigger=True,
        )

        assert result.passed is False
        assert provider.complete_calls == 1
        assert reviewer.shadow_floor_trigger_count == 1
        assert reviewer.floor_override_count == 0
        assert reviewer.floor_override_rate == 0.0
