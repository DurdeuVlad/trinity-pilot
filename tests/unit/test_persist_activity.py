"""Unit tests for persist_attempt activity."""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

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

from trinity_pilot.core.types import AttemptLog, FailureReason  # noqa: E402
from trinity_pilot.workflow.activities import persist_attempt  # noqa: E402


class TestPersistAttemptActivity:
    async def test_persist_passed_attempt_calls_store_save(self):
        saved_logs: list[AttemptLog] = []

        def _capture_save(log: AttemptLog) -> None:
            saved_logs.append(log)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake", "DB_PATH": ":memory:"}):
            with patch(
                "trinity_pilot.memory.evidence_store.EvidenceStore.save",
                side_effect=_capture_save,
            ):
                attempt_id = await persist_attempt(
                    "task-1", "obj-1", 1, "passed", {"stdout": "ok"}, None
                )

        assert attempt_id  # non-empty UUID string
        assert len(saved_logs) == 1
        log = saved_logs[0]
        assert log.task_id == "task-1"
        assert log.objective_id == "obj-1"
        assert log.attempt_number == 1
        assert log.status == "passed"
        assert log.failure_reason is None

    async def test_persist_failed_attempt_with_failure_reason(self):
        saved_logs: list[AttemptLog] = []

        def _capture_save(log: AttemptLog) -> None:
            saved_logs.append(log)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake", "DB_PATH": ":memory:"}):
            with patch(
                "trinity_pilot.memory.evidence_store.EvidenceStore.save",
                side_effect=_capture_save,
            ):
                await persist_attempt(
                    "task-2", "obj-2", 2, "failed",
                    {"stdout": "", "exit_code": 1},
                    "wrong_output",
                )

        assert len(saved_logs) == 1
        log = saved_logs[0]
        assert log.status == "failed"
        assert log.failure_reason == FailureReason.WRONG_OUTPUT
