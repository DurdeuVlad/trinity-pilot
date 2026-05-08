"""TaskWorkflow query method tests — no Temporal runtime needed."""
from __future__ import annotations

from unittest.mock import patch

# TaskWorkflow uses `from temporalio import workflow` at module level via `workflow.defn`.
# We stub temporalio so the class can be imported without the package installed.
import sys
from types import ModuleType

import pytest


def _stub_temporalio():
    """Create minimal temporalio stubs so TaskWorkflow can be imported."""
    if "temporalio" in sys.modules:
        return  # already installed or already stubbed

    temporal_mod = ModuleType("temporalio")
    workflow_mod = ModuleType("temporalio.workflow")
    common_mod = ModuleType("temporalio.common")
    activity_mod = ModuleType("temporalio.activity")
    exceptions_mod = ModuleType("temporalio.exceptions")

    # workflow decorators — all no-ops
    workflow_mod.defn = lambda cls: cls
    workflow_mod.run = lambda fn: fn
    workflow_mod.signal = lambda fn: fn
    workflow_mod.query = lambda fn: fn
    workflow_mod.info = lambda: type("Info", (), {"workflow_id": "test"})()
    workflow_mod.execute_activity = None  # not called in unit tests

    class _UnsafeCtx:
        def imports_passed_through(self):
            import contextlib
            return contextlib.nullcontext()

    workflow_mod.unsafe = _UnsafeCtx()

    common_mod.RetryPolicy = type("RetryPolicy", (), {"__init__": lambda self, **kw: None})

    # activity decorator — no-op
    activity_mod.defn = lambda fn: fn

    # ApplicationError stub
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


_stub_temporalio()

from trinity_pilot.workflow.task_workflow import TaskWorkflow  # noqa: E402


class TestTaskWorkflowCompletedObjectives:
    def test_completed_objectives_empty_at_init(self):
        wf = TaskWorkflow()
        assert wf.completed_objectives() == []

    def test_completed_objectives_reflects_internal_list(self):
        wf = TaskWorkflow()
        wf._completed_objectives.append("obj-a")
        wf._completed_objectives.append("obj-b")
        result = wf.completed_objectives()
        assert result == ["obj-a", "obj-b"]

    def test_completed_objectives_returns_copy(self):
        wf = TaskWorkflow()
        wf._completed_objectives.append("obj-1")
        result = wf.completed_objectives()
        result.append("should-not-appear")
        # Mutating returned list must not affect internal state
        assert wf.completed_objectives() == ["obj-1"]

    def test_get_status_running_at_init(self):
        wf = TaskWorkflow()
        assert wf.get_status() == "running"

    def test_get_status_after_cancel(self):
        wf = TaskWorkflow()
        wf.cancel()
        assert wf.get_status() == "cancelled"

    def test_current_objective_empty_at_init(self):
        wf = TaskWorkflow()
        assert wf.current_objective() == ""


class TestTaskWorkflowCancelledResults:
    def test_cancelled_sets_flag(self):
        wf = TaskWorkflow()
        assert wf._cancelled is False
        wf.cancel()
        assert wf._cancelled is True

    def test_cancel_idempotent(self):
        wf = TaskWorkflow()
        wf.cancel()
        wf.cancel()
        assert wf._cancelled is True
        assert wf.get_status() == "cancelled"
