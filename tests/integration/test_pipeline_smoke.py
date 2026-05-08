"""In-process pipeline smoke test.

Exercises: planner → terminal worker → reviewer → evidence store → reflection store
LLM calls mocked. TerminalWorker runs a real echo subprocess.
No Temporal server needed.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.core.types import (
    AttemptLog,
    DomainType,
    FailureReason,
    ObjectiveSpec,
    ReviewResult,
    RiskClass,
)
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.memory.evidence_store import EvidenceStore
from trinity_pilot.memory.reflection import ReflectionStore
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer
from trinity_pilot.workers.terminal_worker import TerminalWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _terminal_spec(objective_id: str = "smoke-obj") -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id=objective_id,
        goal="run `echo hello-smoke`",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["stdout contains hello-smoke"],
        evidence_bundle=["stdout"],
        max_attempts=2,
        rollback_or_abort_rule="abort",
        metadata={},
    )


_PLAN_JSON = json.dumps([
    {
        "objective_id": "smoke-obj",
        "goal": "run `echo hello-smoke`",
        "dependencies": [],
        "domain": "terminal",
        "required_capabilities": [],
        "risk_class": "low",
        "preconditions": [],
        "success_tests": ["stdout contains hello-smoke"],
        "evidence_bundle": ["stdout"],
        "max_attempts": 2,
        "rollback_or_abort_rule": "abort",
        "metadata": {},
    }
])

_REVIEW_PASS_JSON = json.dumps({
    "passed": True,
    "failure_reason": None,
    "notes": "stdout contains expected output",
    "recovery_hint": "",
})

_REVIEW_FAIL_JSON = json.dumps({
    "passed": False,
    "failure_reason": "failed_assertion",
    "notes": "output missing",
    "recovery_hint": "check command",
})


class MockLLMProvider(LLMProvider):
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)

    async def complete(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        return LLMResponse(content=next(self._responses))

    async def complete_with_tools(self, messages, tools, system="") -> LLMResponse:
        return LLMResponse(content=next(self._responses))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineSmoke:
    @pytest.mark.asyncio
    async def test_terminal_plan_execute_review_passes(self, tmp_path: Path):
        """Full pipeline: planner → terminal worker → reviewer → evidence saved."""
        task_id = str(uuid.uuid4())

        # Planner with mocked LLM
        planner_provider = MockLLMProvider([_PLAN_JSON])
        planner = ObjectivePlanner(provider=planner_provider)
        specs = await planner.plan("echo hello-smoke in a terminal")

        assert len(specs) >= 1
        spec = specs[0]
        assert spec.domain == DomainType.TERMINAL

        # Execute via TerminalWorker (real subprocess)
        worker = TerminalWorker()
        evidence = await worker.execute(spec)

        assert evidence["exit_code"] == 0
        assert "hello-smoke" in evidence["stdout"]

        # Review with mocked LLM
        reviewer_provider = MockLLMProvider([_REVIEW_PASS_JSON])
        reviewer = ObjectiveReviewer(provider=reviewer_provider)
        result = await reviewer.review(spec=spec, evidence=evidence)

        assert result.passed is True

        # Persist evidence
        evidence_store = EvidenceStore(db_path=":memory:", base_dir=tmp_path / "evidence")
        log = AttemptLog(
            attempt_id=str(uuid.uuid4()),
            objective_id=spec.objective_id,
            task_id=task_id,
            attempt_number=1,
            status="passed",
            failure_reason=None,
            evidence=evidence,
        )
        evidence_store.save(log)

        loaded = evidence_store.load_attempt_evidence(task_id, spec.objective_id, 1)
        assert loaded["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_terminal_failure_saves_reflection(self, tmp_path: Path):
        """On review failure, reflection is saved with recovery_hint."""
        task_id = str(uuid.uuid4())
        spec = _terminal_spec()

        # Simulate worker returning valid evidence
        worker = TerminalWorker()
        evidence = await worker.execute(spec)

        # Reviewer returns failure
        reviewer_provider = MockLLMProvider([_REVIEW_FAIL_JSON])
        reviewer = ObjectiveReviewer(provider=reviewer_provider)
        result = await reviewer.review(spec=spec, evidence=evidence)

        assert result.passed is False

        # Save reflection
        reflection_store = ReflectionStore()
        reflection_store.save_reflection(
            objective_id=spec.objective_id,
            task_id=task_id,
            attempt_number=1,
            failure_reason=result.failure_reason.value if result.failure_reason else None,
            notes=result.notes,
            recovery_hint=result.recovery_hint,
        )

        reflections = reflection_store.get_reflections(spec.objective_id)
        assert len(reflections) == 1
        assert reflections[0]["recovery_hint"] == "check command"
