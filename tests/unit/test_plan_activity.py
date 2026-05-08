"""Unit tests for plan_objectives activity — verifies ApplicationError on PlanningError."""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest


def _ensure_temporalio_stubbed():
    """Stub temporalio if not installed so activities.py can be imported."""
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

from trinity_pilot.workflow.activities import plan_objectives  # noqa: E402


class TestPlanObjectivesActivity:
    async def test_planning_error_raises_application_error(self):
        """PlanningError from planner must surface as ApplicationError('planning_failed')."""
        from temporalio.exceptions import ApplicationError
        from trinity_pilot.planner.planner import PlanningError

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            with patch(
                "trinity_pilot.workflow.activities.ObjectivePlanner.plan",
                new_callable=AsyncMock,
                side_effect=PlanningError("invalid JSON from LLM"),
            ):
                with pytest.raises(ApplicationError) as exc_info:
                    await plan_objectives("do something")
        assert exc_info.value.type == "planning_failed"

    async def test_planning_error_is_non_retryable(self):
        """ApplicationError raised from plan_objectives must be non_retryable."""
        from temporalio.exceptions import ApplicationError
        from trinity_pilot.planner.planner import PlanningError

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
            with patch(
                "trinity_pilot.workflow.activities.ObjectivePlanner.plan",
                new_callable=AsyncMock,
                side_effect=PlanningError("bad JSON"),
            ):
                with pytest.raises(ApplicationError) as exc_info:
                    await plan_objectives("anything")
        assert exc_info.value.non_retryable is True
