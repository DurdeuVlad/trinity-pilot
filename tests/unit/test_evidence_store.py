"""EvidenceStore unit tests — uses tmp directory, no real DB path needed."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from trinity_pilot.core.types import AttemptLog, FailureReason
from trinity_pilot.memory.evidence_store import EvidenceStore, _evidence_dir


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
        with patch("trinity_pilot.memory.evidence_store._EVIDENCE_ROOT", tmp_path):
            store = EvidenceStore(":memory:")
            log = _log()
            store.save(log)

            evidence_file = tmp_path / "task-1" / "obj-1" / "attempt_1" / "evidence.json"
            assert evidence_file.exists()
            data = json.loads(evidence_file.read_text())
            assert data["page_title"] == "Test"

    def test_load_attempt_evidence_returns_saved_data(self, tmp_path):
        with patch("trinity_pilot.memory.evidence_store._EVIDENCE_ROOT", tmp_path):
            store = EvidenceStore(":memory:")
            log = _log(evidence={"stdout": "hello", "exit_code": 0})
            store.save(log)

            loaded = store.load_attempt_evidence("task-1", "obj-1", 1)
            assert loaded["stdout"] == "hello"
            assert loaded["exit_code"] == 0

    def test_load_nonexistent_returns_empty_dict(self, tmp_path):
        with patch("trinity_pilot.memory.evidence_store._EVIDENCE_ROOT", tmp_path):
            store = EvidenceStore(":memory:")
            result = store.load_attempt_evidence("no-task", "no-obj", 99)
            assert result == {}

    def test_large_binary_field_written_to_separate_file(self, tmp_path):
        with patch("trinity_pilot.memory.evidence_store._EVIDENCE_ROOT", tmp_path):
            store = EvidenceStore(":memory:")
            large_b64 = "A" * 1000  # > 256 chars
            log = _log(evidence={"screenshot": large_b64})
            store.save(log)

            bin_file = tmp_path / "task-1" / "obj-1" / "attempt_1" / "screenshot.bin"
            assert bin_file.exists()

    def test_multiple_attempts_separate_directories(self, tmp_path):
        with patch("trinity_pilot.memory.evidence_store._EVIDENCE_ROOT", tmp_path):
            store = EvidenceStore(":memory:")
            store.save(_log(attempt_number=1))
            store.save(_log(attempt_number=2))

            assert (tmp_path / "task-1" / "obj-1" / "attempt_1" / "evidence.json").exists()
            assert (tmp_path / "task-1" / "obj-1" / "attempt_2" / "evidence.json").exists()
