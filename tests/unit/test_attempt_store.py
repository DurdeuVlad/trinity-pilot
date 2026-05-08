"""AttemptStore unit tests."""
from __future__ import annotations

import uuid

from trinity_pilot.core.types import AttemptLog, FailureReason
from trinity_pilot.memory.store import AttemptStore


def _log(
    task_id: str = "task-1",
    objective_id: str = "obj-1",
    attempt_number: int = 1,
) -> AttemptLog:
    return AttemptLog(
        attempt_id=str(uuid.uuid4()),
        task_id=task_id,
        objective_id=objective_id,
        attempt_number=attempt_number,
        status="failed",
        failure_reason=FailureReason.WRONG_OUTPUT,
        evidence={"stdout": "oops"},
    )


class TestAttemptStoreGetByTask:
    def test_get_attempts_by_task_returns_all(self):
        store = AttemptStore(":memory:")
        store.log_attempt(_log(task_id="t-a", objective_id="obj-1", attempt_number=1))
        store.log_attempt(_log(task_id="t-a", objective_id="obj-2", attempt_number=1))
        store.log_attempt(_log(task_id="t-b", objective_id="obj-1", attempt_number=1))

        results = store.get_attempts_by_task("t-a")
        assert len(results) == 2
        task_ids = {r.task_id for r in results}
        assert task_ids == {"t-a"}

    def test_get_attempts_by_task_empty_for_unknown(self):
        store = AttemptStore(":memory:")
        assert store.get_attempts_by_task("ghost") == []

    def test_get_attempts_ordered_by_attempt_number(self):
        store = AttemptStore(":memory:")
        # Insert out of order
        store.log_attempt(_log(task_id="t", objective_id="obj", attempt_number=3))
        store.log_attempt(_log(task_id="t", objective_id="obj", attempt_number=1))
        store.log_attempt(_log(task_id="t", objective_id="obj", attempt_number=2))

        results = store.get_attempts("obj")
        numbers = [r.attempt_number for r in results]
        assert numbers == [1, 2, 3]

    def test_get_attempts_by_task_ordered_by_objective_then_attempt(self):
        store = AttemptStore(":memory:")
        store.log_attempt(_log(task_id="t", objective_id="obj-b", attempt_number=1))
        store.log_attempt(_log(task_id="t", objective_id="obj-a", attempt_number=2))
        store.log_attempt(_log(task_id="t", objective_id="obj-a", attempt_number=1))

        results = store.get_attempts_by_task("t")
        assert results[0].objective_id == "obj-a"
        assert results[0].attempt_number == 1
        assert results[1].objective_id == "obj-a"
        assert results[1].attempt_number == 2
        assert results[2].objective_id == "obj-b"
