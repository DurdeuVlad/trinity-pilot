"""Real reviewer test — calls live Gemini API via ObjectiveReviewer."""
import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer

pytestmark = pytest.mark.real


def _terminal_spec() -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="reviewer-smoke",
        goal="run `echo hello`",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["stdout contains 'hello'"],
        evidence_bundle=["stdout"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
        metadata={},
    )


async def test_reviewer_returns_result_for_passing_evidence(gemini_api_key):
    provider = GeminiProvider(api_key=gemini_api_key, model="gemini-2.5-flash")
    reviewer = ObjectiveReviewer(provider=provider)

    evidence = {
        "domain": "terminal",
        "objective_id": "reviewer-smoke",
        "stdout": "hello\n",
        "stderr": "",
        "exit_code": 0,
        "created_files": [],
        "workspace": "/tmp/test",
        "error": None,
    }

    result = await reviewer.review(spec=_terminal_spec(), evidence=evidence)

    assert isinstance(result.passed, bool)
    # With clear passing evidence, expect passed=True
    assert result.passed is True


async def test_reviewer_returns_result_for_failing_evidence(gemini_api_key):
    provider = GeminiProvider(api_key=gemini_api_key, model="gemini-2.5-flash")
    reviewer = ObjectiveReviewer(provider=provider)

    evidence = {
        "domain": "terminal",
        "objective_id": "reviewer-smoke",
        "stdout": "",
        "stderr": "command not found",
        "exit_code": 127,
        "created_files": [],
        "workspace": "/tmp/test",
        "error": "exit code 127",
    }

    result = await reviewer.review(spec=_terminal_spec(), evidence=evidence)

    assert isinstance(result.passed, bool)
    if not result.passed:
        assert result.failure_reason is not None
