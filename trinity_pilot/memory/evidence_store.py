from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from trinity_pilot.core.types import AttemptLog
from trinity_pilot.memory.store import AttemptStore

_DEFAULT_EVIDENCE_ROOT = Path.home() / ".trinity-pilot" / "evidence"


def _evidence_dir(base: Path, task_id: str, objective_id: str, attempt_number: int) -> Path:
    return base / task_id / objective_id / f"attempt_{attempt_number}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class EvidenceStore:
    def __init__(
        self,
        db_path: str | Path = ":memory:",
        base_dir: Path | None = None,
    ) -> None:
        self._attempt_store = AttemptStore(db_path)
        self._base_dir = base_dir if base_dir is not None else _DEFAULT_EVIDENCE_ROOT

    def save(self, log: AttemptLog) -> None:
        self._attempt_store.log_attempt(log)
        self._persist_files(log)

    def _persist_files(self, log: AttemptLog) -> None:
        evidence_dir = _evidence_dir(self._base_dir, log.task_id, log.objective_id, log.attempt_number)
        evidence_json = json.dumps(log.evidence, ensure_ascii=False, indent=2)
        _atomic_write(evidence_dir / "evidence.json", evidence_json.encode())

        for key in ("screenshot", "dom_snapshot", "trace_path"):
            value = log.evidence.get(key)
            if value and isinstance(value, str) and len(value) > 256:
                _atomic_write(evidence_dir / f"{key}.bin", value.encode())

    def load_attempt_evidence(
        self, task_id: str, objective_id: str, attempt_number: int
    ) -> dict[str, Any]:
        evidence_file = (
            _evidence_dir(self._base_dir, task_id, objective_id, attempt_number)
            / "evidence.json"
        )
        if not evidence_file.exists():
            return {}
        return json.loads(evidence_file.read_text(encoding="utf-8"))

    def list_attempts(self, task_id: str) -> list[Any]:
        """Return all AttemptLog records for a task from the database."""
        return self._attempt_store.get_attempts_by_task(task_id)
