"""Unit tests for save_reflection_activity."""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import patch

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

from trinity_pilot.workflow.activities import save_reflection_activity  # noqa: E402


class TestSaveReflectionActivity:
    async def test_save_reflection_called_with_correct_args(self):
        calls: list[dict] = []

        def _capture(
            objective_id, task_id, attempt_number,
            failure_reason, notes, recovery_hint,
        ):
            calls.append({
                "objective_id": objective_id,
                "task_id": task_id,
                "attempt_number": attempt_number,
                "failure_reason": failure_reason,
                "notes": notes,
                "recovery_hint": recovery_hint,
            })
            return "fake-uuid"

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake", "DB_PATH": ":memory:"}):
            with patch(
                "trinity_pilot.memory.reflection.ReflectionStore.save_reflection",
                side_effect=_capture,
            ):
                await save_reflection_activity(
                    task_id="task-1",
                    objective_id="obj-1",
                    attempt_number=2,
                    failure_reason="wrong_output",
                    notes="stdout mismatch",
                    recovery_hint="check the command",
                )

        assert len(calls) == 1
        c = calls[0]
        assert c["task_id"] == "task-1"
        assert c["objective_id"] == "obj-1"
        assert c["attempt_number"] == 2
        assert c["failure_reason"] == "wrong_output"
        assert c["notes"] == "stdout mismatch"
        assert c["recovery_hint"] == "check the command"

    async def test_save_reflection_with_null_failure_reason(self):
        calls: list[dict] = []

        def _capture(objective_id, task_id, attempt_number, failure_reason, notes, recovery_hint):
            calls.append({"failure_reason": failure_reason})
            return "fake-uuid"

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake", "DB_PATH": ":memory:"}):
            with patch(
                "trinity_pilot.memory.reflection.ReflectionStore.save_reflection",
                side_effect=_capture,
            ):
                await save_reflection_activity(
                    task_id="t", objective_id="o", attempt_number=1,
                    failure_reason=None, notes="", recovery_hint="",
                )

        assert calls[0]["failure_reason"] is None
