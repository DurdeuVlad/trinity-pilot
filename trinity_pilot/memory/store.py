from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from trinity_pilot.core.types import (
    AttemptLog,
    FailureReason,
    ObjectiveSpec,
    TaskRecord,
    TaskStatus,
)
from trinity_pilot.memory.db import open_db


class TaskStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn: sqlite3.Connection = open_db(db_path)

    def save_task(self, task: TaskRecord) -> None:
        objectives_json = json.dumps([o.to_dict() for o in task.objectives])
        self._conn.execute(
            """
            INSERT OR REPLACE INTO tasks (task_id, user_request, status, objectives_json)
            VALUES (?, ?, ?, ?)
            """,
            (task.task_id, task.user_request, task.status.value, objectives_json),
        )
        self._conn.commit()

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        self._conn.execute(
            "UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
            (status.value, task_id),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if not row:
            return None
        objectives = [
            ObjectiveSpec.from_dict(o) for o in json.loads(row["objectives_json"])
        ]
        return TaskRecord(
            task_id=row["task_id"],
            user_request=row["user_request"],
            objectives=objectives,
            status=TaskStatus(row["status"]),
        )

    def search(self, query: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT task_id FROM task_fts WHERE task_fts MATCH ? ORDER BY rank",
            (query,),
        ).fetchall()
        return [r["task_id"] for r in rows]

    def close(self) -> None:
        self._conn.close()


class AttemptStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn: sqlite3.Connection = open_db(db_path)

    def log_attempt(self, log: AttemptLog) -> None:
        evidence_json = json.dumps(log.evidence)
        failure_reason = log.failure_reason.value if log.failure_reason else None
        self._conn.execute(
            """
            INSERT OR REPLACE INTO attempt_logs
            (attempt_id, task_id, objective_id, attempt_number, status, failure_reason, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.attempt_id,
                log.task_id,
                log.objective_id,
                log.attempt_number,
                log.status,
                failure_reason,
                evidence_json,
            ),
        )
        self._conn.commit()

    def get_attempts(self, objective_id: str) -> list[AttemptLog]:
        rows = self._conn.execute(
            "SELECT * FROM attempt_logs WHERE objective_id=? ORDER BY attempt_number",
            (objective_id,),
        ).fetchall()
        result = []
        for row in rows:
            fr = FailureReason(row["failure_reason"]) if row["failure_reason"] else None
            result.append(
                AttemptLog(
                    attempt_id=row["attempt_id"],
                    objective_id=row["objective_id"],
                    task_id=row["task_id"],
                    attempt_number=row["attempt_number"],
                    status=row["status"],
                    failure_reason=fr,
                    evidence=json.loads(row["evidence_json"]),
                )
            )
        return result

    def close(self) -> None:
        self._conn.close()
