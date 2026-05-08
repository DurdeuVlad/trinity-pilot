"""ReflectionStore unit tests — all in-memory SQLite."""
from __future__ import annotations

import uuid

import pytest

from trinity_pilot.memory.reflection import ReflectionStore


class TestReflectionStore:
    def test_save_and_retrieve_reflection(self):
        store = ReflectionStore(":memory:")
        rid = store.save_reflection(
            objective_id="obj-1",
            task_id="task-1",
            attempt_number=1,
            failure_reason="missing_artifact",
            notes="screenshot missing",
            recovery_hint="ensure screenshot capability is available",
        )
        assert rid

        reflections = store.get_reflections("obj-1")
        assert len(reflections) == 1
        assert reflections[0]["notes"] == "screenshot missing"
        assert reflections[0]["recovery_hint"] == "ensure screenshot capability is available"
        assert reflections[0]["failure_reason"] == "missing_artifact"

    def test_empty_returns_empty_list(self):
        store = ReflectionStore(":memory:")
        assert store.get_reflections("no-obj") == []

    def test_multiple_reflections_ordered_by_attempt(self):
        store = ReflectionStore(":memory:")
        store.save_reflection("obj-2", "t-1", 2, "wrong_output", "wrong", "try again")
        store.save_reflection("obj-2", "t-1", 1, "missing_artifact", "missing", "add cap")

        reflections = store.get_reflections("obj-2")
        assert len(reflections) == 2
        assert reflections[0]["attempt_number"] == 1
        assert reflections[1]["attempt_number"] == 2

    def test_reflections_isolated_by_objective_id(self):
        store = ReflectionStore(":memory:")
        store.save_reflection("obj-a", "t-1", 1, None, "note a", "hint a")
        store.save_reflection("obj-b", "t-1", 1, None, "note b", "hint b")

        assert len(store.get_reflections("obj-a")) == 1
        assert len(store.get_reflections("obj-b")) == 1

    def test_null_failure_reason_stored(self):
        store = ReflectionStore(":memory:")
        store.save_reflection("obj-3", "t-1", 1, None, "passed", "")
        r = store.get_reflections("obj-3")[0]
        assert r["failure_reason"] is None

    def test_close_and_reopen_persists_data(self, tmp_path):
        db_path = str(tmp_path / "reflections.db")
        store = ReflectionStore(db_path)
        store.save_reflection("obj-persist", "t-1", 1, None, "note", "hint")
        store.close()

        store2 = ReflectionStore(db_path)
        reflections = store2.get_reflections("obj-persist")
        assert len(reflections) == 1
        assert reflections[0]["notes"] == "note"
        store2.close()

    def test_get_all_reflections_returns_all_for_task(self):
        store = ReflectionStore(":memory:")
        store.save_reflection("obj-a", "task-x", 1, None, "note a1", "hint a1")
        store.save_reflection("obj-b", "task-x", 1, "wrong_output", "note b1", "hint b1")
        store.save_reflection("obj-a", "task-x", 2, None, "note a2", "hint a2")
        # Different task — should NOT appear
        store.save_reflection("obj-c", "task-y", 1, None, "note c", "hint c")

        result = store.get_all_reflections("task-x")
        assert len(result) == 3
        objectives = [r["objective_id"] for r in result]
        assert "obj-c" not in objectives

    def test_get_all_reflections_empty_for_unknown_task(self):
        store = ReflectionStore(":memory:")
        assert store.get_all_reflections("no-such-task") == []

    def test_save_reflection_returns_valid_uuid(self):
        store = ReflectionStore(":memory:")
        rid = store.save_reflection("obj-1", "t-1", 1, None, "note", "hint")
        parsed = uuid.UUID(rid)  # raises ValueError if not a valid UUID
        assert str(parsed) == rid

    def test_get_reflections_cross_task_same_obj_id(self):
        """get_reflections queries by obj_id — returns entries from all tasks."""
        store = ReflectionStore(":memory:")
        store.save_reflection("obj-x", "task-alpha", 1, None, "note alpha", "hint alpha")
        store.save_reflection("obj-x", "task-beta", 1, None, "note beta", "hint beta")

        result = store.get_reflections("obj-x")
        assert len(result) == 2
        task_ids = {r["task_id"] for r in result}
        assert task_ids == {"task-alpha", "task-beta"}
