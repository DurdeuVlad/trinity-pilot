"""Unit tests for SQLite memory layer. All in-memory — no filesystem."""
from __future__ import annotations

import pytest

from trinity_pilot.core.types import (
    AttemptLog,
    DomainType,
    FailureReason,
    ObjectiveSpec,
    RiskClass,
    TaskRecord,
    TaskStatus,
)
from trinity_pilot.memory.store import AttemptStore, TaskStore


def _make_spec(obj_id: str = "obj-1") -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id=obj_id,
        goal="Navigate to example.com",
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=["chromium installed"],
        success_tests=["title == 'Example Domain'"],
        evidence_bundle=["screenshot"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


class TestTaskStore:
    def test_save_and_retrieve_task(self):
        store = TaskStore(":memory:")
        task = TaskRecord(task_id="t-1", user_request="open browser")
        store.save_task(task)

        retrieved = store.get_task("t-1")
        assert retrieved is not None
        assert retrieved.task_id == "t-1"
        assert retrieved.user_request == "open browser"
        assert retrieved.status == TaskStatus.PENDING

    def test_save_task_with_objectives(self):
        store = TaskStore(":memory:")
        spec = _make_spec()
        task = TaskRecord(task_id="t-2", user_request="do thing", objectives=[spec])
        store.save_task(task)

        retrieved = store.get_task("t-2")
        assert retrieved is not None
        assert len(retrieved.objectives) == 1
        assert retrieved.objectives[0].objective_id == "obj-1"
        assert retrieved.objectives[0].domain == DomainType.BROWSER

    def test_update_status(self):
        store = TaskStore(":memory:")
        store.save_task(TaskRecord(task_id="t-3", user_request="run task"))
        store.update_status("t-3", TaskStatus.RUNNING)

        task = store.get_task("t-3")
        assert task is not None
        assert task.status == TaskStatus.RUNNING

    def test_get_nonexistent_returns_none(self):
        store = TaskStore(":memory:")
        assert store.get_task("no-such-id") is None

    def test_fts_search(self):
        store = TaskStore(":memory:")
        store.save_task(TaskRecord(task_id="t-a", user_request="open chrome browser"))
        store.save_task(TaskRecord(task_id="t-b", user_request="run python script"))

        results = store.search("chrome")
        assert "t-a" in results
        assert "t-b" not in results

    def test_replace_existing_task(self):
        store = TaskStore(":memory:")
        store.save_task(TaskRecord(task_id="t-dup", user_request="first"))
        store.save_task(TaskRecord(task_id="t-dup", user_request="second"))

        task = store.get_task("t-dup")
        assert task is not None
        assert task.user_request == "second"


class TestAttemptStore:
    def test_log_and_retrieve_attempt(self):
        store = AttemptStore(":memory:")
        log = AttemptLog(
            attempt_id="a-1",
            objective_id="obj-1",
            task_id="t-1",
            attempt_number=1,
            status="failed",
            failure_reason=FailureReason.MISSING_ARTIFACT,
            evidence={"screenshot": "base64data"},
        )
        store.log_attempt(log)

        attempts = store.get_attempts("obj-1")
        assert len(attempts) == 1
        assert attempts[0].status == "failed"
        assert attempts[0].failure_reason == FailureReason.MISSING_ARTIFACT
        assert attempts[0].evidence["screenshot"] == "base64data"

    def test_multiple_attempts_ordered(self):
        store = AttemptStore(":memory:")
        for i in range(1, 4):
            store.log_attempt(
                AttemptLog(
                    attempt_id=f"a-{i}",
                    objective_id="obj-2",
                    task_id="t-1",
                    attempt_number=i,
                    status="failed" if i < 3 else "passed",
                )
            )

        attempts = store.get_attempts("obj-2")
        assert len(attempts) == 3
        assert [a.attempt_number for a in attempts] == [1, 2, 3]
        assert attempts[2].status == "passed"

    def test_attempt_no_failure_reason(self):
        store = AttemptStore(":memory:")
        store.log_attempt(
            AttemptLog(
                attempt_id="a-ok",
                objective_id="obj-3",
                task_id="t-1",
                attempt_number=1,
                status="passed",
            )
        )
        attempts = store.get_attempts("obj-3")
        assert attempts[0].failure_reason is None

    def test_empty_attempts_for_unknown_objective(self):
        store = AttemptStore(":memory:")
        assert store.get_attempts("no-obj") == []
