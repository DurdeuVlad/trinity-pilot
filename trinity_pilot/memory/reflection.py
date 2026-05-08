from __future__ import annotations

import uuid
from pathlib import Path

from trinity_pilot.memory.db import open_db


class ReflectionStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = open_db(db_path)

    def save_reflection(
        self,
        objective_id: str,
        task_id: str,
        attempt_number: int,
        failure_reason: str | None,
        notes: str,
        recovery_hint: str,
    ) -> str:
        reflection_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO reflections
            (reflection_id, objective_id, task_id, attempt_number, failure_reason, notes, recovery_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (reflection_id, objective_id, task_id, attempt_number, failure_reason, notes, recovery_hint),
        )
        self._conn.commit()
        return reflection_id

    def get_reflections(self, objective_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM reflections WHERE objective_id=? ORDER BY attempt_number",
            (objective_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_all_reflections(self, task_id: str) -> list[dict]:
        """Return all reflections for a task, ordered by objective then attempt."""
        rows = self._conn.execute(
            "SELECT * FROM reflections WHERE task_id=? ORDER BY objective_id, attempt_number",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
