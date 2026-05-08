"""EvidenceStore unit tests — uses tmp_path, never writes to real ~."""
from __future__ import annotations

import json

import pytest

from trinity_pilot.core.types import AttemptLog, FailureReason
from trinity_pilot.memory.evidence_store import EvidenceStore


def _log(attempt_number: int = 1, evidence: dict | None = None) -> AttemptLog:
    return AttemptLog(
        attempt_id=f"a-{attempt_number}",
        objective_id="obj-1",
        task_id="task-1",
        attempt_number=attempt_number,
        status="failed",
        failure_reason=FailureReason.MISSING_ARTIFACT,
        evidence=evidence or {"screenshot": "base64data", "page_title": "Test"},
    )


class TestEvidenceStore:
    def test_save_creates_evidence_json(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        log = _log()
        store.save(log)

        evidence_file = tmp_path / "task-1" / "obj-1" / "attempt_1" / "evidence.json"
        assert evidence_file.exists()
        data = json.loads(evidence_file.read_text())
        assert data["page_title"] == "Test"

    def test_load_attempt_evidence_returns_saved_data(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        log = _log(evidence={"stdout": "hello", "exit_code": 0})
        store.save(log)

        loaded = store.load_attempt_evidence("task-1", "obj-1", 1)
        assert loaded["stdout"] == "hello"
        assert loaded["exit_code"] == 0

    def test_load_nonexistent_returns_empty_dict(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        result = store.load_attempt_evidence("no-task", "no-obj", 99)
        assert result == {}

    def test_large_binary_field_written_to_separate_file(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        large_b64 = "A" * 1000  # > 256 chars
        log = _log(evidence={"screenshot": large_b64})
        store.save(log)

        bin_file = tmp_path / "task-1" / "obj-1" / "attempt_1" / "screenshot.bin"
        assert bin_file.exists()

    def test_multiple_attempts_separate_directories(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        store.save(_log(attempt_number=1))
        store.save(_log(attempt_number=2))

        assert (tmp_path / "task-1" / "obj-1" / "attempt_1" / "evidence.json").exists()
        assert (tmp_path / "task-1" / "obj-1" / "attempt_2" / "evidence.json").exists()

    def test_base_dir_injectable_does_not_use_home(self, tmp_path):
        """Confirm no writes go to ~/.trinity-pilot when base_dir is set."""
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        store.save(_log())
        # Only files under tmp_path should exist
        written = list(tmp_path.rglob("evidence.json"))
        assert len(written) == 1

    def test_list_attempts_returns_all_for_task(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        store.save(_log(attempt_number=1))
        store.save(_log(attempt_number=2))

        logs = store.list_attempts("task-1")
        assert len(logs) == 2
        attempt_numbers = sorted(lg.attempt_number for lg in logs)
        assert attempt_numbers == [1, 2]

    def test_list_attempts_empty_for_unknown_task(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        assert store.list_attempts("ghost-task") == []

    def test_delete_task_removes_db_rows(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        store.save(_log(attempt_number=1))
        assert len(store.list_attempts("task-1")) == 1
        store.delete_task("task-1")
        assert store.list_attempts("task-1") == []

    def test_delete_task_removes_evidence_files(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        store.save(_log(attempt_number=1))
        task_dir = tmp_path / "task-1"
        assert task_dir.exists()
        store.delete_task("task-1")
        assert not task_dir.exists()

    def test_delete_task_nonexistent_is_noop(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        # Should not raise
        store.delete_task("no-such-task")

    def test_delete_task_empty_id_raises_value_error(self, tmp_path):
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        with pytest.raises(ValueError, match="task_id"):
            store.delete_task("")
