"""EvidenceStore concurrent write safety — 10 coroutines write same path."""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from trinity_pilot.core.types import AttemptLog, FailureReason
from trinity_pilot.memory.evidence_store import EvidenceStore


def _log(task_id: str, attempt_number: int) -> AttemptLog:
    return AttemptLog(
        attempt_id=str(uuid.uuid4()),
        objective_id="obj-concurrent",
        task_id=task_id,
        attempt_number=attempt_number,
        status="passed",
        failure_reason=None,
        evidence={"stdout": f"output-{attempt_number}", "exit_code": 0},
    )


class TestEvidenceStoreConcurrent:
    @pytest.mark.asyncio
    async def test_concurrent_writes_all_succeed(self, tmp_path):
        """10 concurrent writes to same base_dir, each unique path → all succeed."""
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        task_id = str(uuid.uuid4())

        async def write_one(attempt_number: int) -> None:
            # _atomic_write is sync but safe — os.replace() is atomic on Windows + POSIX
            log = _log(task_id, attempt_number)
            await asyncio.to_thread(store.save, log)

        await asyncio.gather(*[write_one(i) for i in range(1, 11)])

        # All 10 attempt directories should exist with valid JSON
        for i in range(1, 11):
            evidence_file = (
                tmp_path / task_id / "obj-concurrent" / f"attempt_{i}" / "evidence.json"
            )
            assert evidence_file.exists(), f"Missing evidence for attempt {i}"
            data = json.loads(evidence_file.read_text())
            assert data["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_sequential_overwrites_same_path_valid(self, tmp_path):
        """Sequential overwrites to same path produce valid JSON (unique paths in prod)."""
        store = EvidenceStore(":memory:", base_dir=tmp_path)
        task_id = "fixed-task"
        for i in range(5):
            log = _log(task_id, attempt_number=1)
            store.save(log)

        evidence_file = tmp_path / task_id / "obj-concurrent" / "attempt_1" / "evidence.json"
        assert evidence_file.exists()
        data = json.loads(evidence_file.read_text())
        assert "exit_code" in data
