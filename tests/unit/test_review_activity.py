"""Unit tests for review_objective activity."""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest


def _ensure_temporalio_stubbed():
    if "temporalio" in sys.modules:
        return
    temporal_mod = ModuleType("temporalio")
    workflow_mod = ModuleType("temporalio.workflow")
    common_mod = ModuleType("temporalio.common")
    activity_mod = ModuleType("temporalio.activity")
    exceptions_mod = ModuleType("temporalio.exceptions")
    workflow_mod.defn = lambda cls: cls
    workflow_mod.run = lambda fn: fn
    workflow_mod.signal = lambda fn: fn
    workflow_mod.query = lambda fn: fn
    workflow_mod.info = lambda: type("Info", (), {"workflow_id": "test"})()
    workflow_mod.execute_activity = None

    class _UnsafeCtx:
        def imports_passed_through(self):
            import contextlib
            return contextlib.nullcontext()

    workflow_mod.unsafe = _UnsafeCtx()
    common_mod.RetryPolicy = type("RetryPolicy", (), {"__init__": lambda self, **kw: None})
    activity_mod.defn = lambda fn: fn

    class ApplicationError(Exception):
        def __init__(self, type_: str, *args, non_retryable: bool = False, **kw):
            super().__init__(*args)
            self.type = type_
            self.non_retryable = non_retryable

    exceptions_mod.ApplicationError = ApplicationError
    temporal_mod.workflow = workflow_mod
    temporal_mod.activity = activity_mod
    sys.modules["temporalio"] = temporal_mod
    sys.modules["temporalio.workflow"] = workflow_mod
    sys.modules["temporalio.common"] = common_mod
    sys.modules["temporalio.activity"] = activity_mod
    sys.modules["temporalio.exceptions"] = exceptions_mod


_ensure_temporalio_stubbed()

from trinity_pilot.core.types import DomainType, FailureReason, ObjectiveSpec, ReviewResult, RiskClass  # noqa: E402
from trinity_pilot.workflow.activities import review_objective  # noqa: E402


def _spec_dict() -> dict:
    return ObjectiveSpec(
        objective_id="obj-1",
        goal="echo hello",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["stdout contains hello"],
        evidence_bundle=["stdout"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    ).to_dict()


def _evidence() -> dict:
    return {
        "domain": "terminal",
        "objective_id": "obj-1",
        "stdout": "hello\n",
        "stderr": "",
        "exit_code": 0,
        "created_files": [],
        "workspace": "/tmp",
        "error": None,
    }


class TestReviewObjectiveActivity:
    async def test_passing_review_returns_passed_true(self):
        passing_result = ReviewResult(passed=True)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            with patch(
                "trinity_pilot.workflow.activities.ObjectiveReviewer.review",
                new_callable=AsyncMock,
                return_value=passing_result,
            ):
                result = await review_objective(_spec_dict(), _evidence())
        assert result["passed"] is True
        assert result["failure_reason"] is None

    async def test_failing_review_returns_failure_reason(self):
        failing_result = ReviewResult(
            passed=False,
            failure_reason=FailureReason.WRONG_OUTPUT,
            notes="output mismatch",
            recovery_hint="check stdout",
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            with patch(
                "trinity_pilot.workflow.activities.ObjectiveReviewer.review",
                new_callable=AsyncMock,
                return_value=failing_result,
            ):
                result = await review_objective(_spec_dict(), _evidence())
        assert result["passed"] is False
        assert result["failure_reason"] == "wrong_output"
        assert result["notes"] == "output mismatch"
        assert result["recovery_hint"] == "check stdout"
