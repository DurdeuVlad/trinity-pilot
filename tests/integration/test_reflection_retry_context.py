"""Integration test: ReflectionStore → retry_context round-trip."""
import json

import pytest

from trinity_pilot.memory.reflection import ReflectionStore


class TestReflectionRetryContext:
    def test_two_reflections_appear_in_retry_context(self):
        store = ReflectionStore()  # in-memory

        store.save_reflection(
            objective_id="obj-1",
            task_id="task-abc",
            attempt_number=1,
            failure_reason="failed_assertion",
            notes="Button not found",
            recovery_hint="Try scrolling down first",
        )
        store.save_reflection(
            objective_id="obj-1",
            task_id="task-abc",
            attempt_number=2,
            failure_reason="ui_state_mismatch",
            notes="Page still loading",
            recovery_hint="Add explicit wait before interaction",
        )

        reflections = store.get_reflections("obj-1")
        assert len(reflections) == 2

        retry_context = json.dumps(reflections)
        parsed = json.loads(retry_context)

        hints = [r["recovery_hint"] for r in parsed]
        assert "Try scrolling down first" in hints
        assert "Add explicit wait before interaction" in hints

        # Ordered by attempt_number ascending
        assert parsed[0]["attempt_number"] == 1
        assert parsed[1]["attempt_number"] == 2
