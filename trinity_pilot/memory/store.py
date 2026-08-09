from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from trinity_pilot.core.types import (
    AttemptLog,
    FailureReason,
    ObjectiveSpec,
    TaskRecord,
    TaskStatus,
)
from trinity_pilot.memory.db import open_db
from trinity_pilot.orchestrator.fsm import ObjectiveState


class TaskStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn: sqlite3.Connection = open_db(db_path)
        # AttemptStore/ObjectiveStateStore already serialize their writes with a
        # lock; this one didn't, despite check_same_thread=False allowing any
        # async task/thread to use the connection concurrently — interleaved
        # execute()/commit() calls from different tasks could produce
        # non-atomic multi-statement sequences. Matches the existing pattern.
        self._lock = threading.Lock()

    def save_task(self, task: TaskRecord) -> None:
        objectives_json = json.dumps([o.to_dict() for o in task.objectives])
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO tasks (task_id, user_request, status, objectives_json)
                VALUES (?, ?, ?, ?)
                """,
                (task.task_id, task.user_request, task.status.value, objectives_json),
            )
            self._conn.commit()

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                (status.value, task_id),
            )
            self._conn.commit()

    def mark_orphaned_running_as_interrupted(self) -> list[str]:
        """Resolve any task left at RUNNING by a prior crash (process kill, power
        loss — anything that skipped the normal completion/failure path).

        Without this, a crashed run leaves a RUNNING row forever with nothing
        checking it later — the user has no signal that a specific task was
        left mid-flight on their next launch. Call once at orchestrator startup.
        Returns the task_ids that were resolved.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_id FROM tasks WHERE status=?", (TaskStatus.RUNNING.value,)
            ).fetchall()
            task_ids = [row["task_id"] for row in rows]
            if task_ids:
                self._conn.executemany(
                    "UPDATE tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                    [(TaskStatus.FAILED.value, task_id) for task_id in task_ids],
                )
                self._conn.commit()
            return task_ids

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

    def list_tasks(self, status: "TaskStatus | None" = None) -> list["TaskRecord"]:
        """Return all tasks, optionally filtered by status."""
        if status is None:
            rows = self._conn.execute("SELECT * FROM tasks").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status=?", (status.value,)
            ).fetchall()
        result = []
        for row in rows:
            objectives = [
                ObjectiveSpec.from_dict(o) for o in json.loads(row["objectives_json"])
            ]
            result.append(
                TaskRecord(
                    task_id=row["task_id"],
                    user_request=row["user_request"],
                    objectives=objectives,
                    status=TaskStatus(row["status"]),
                )
            )
        return result

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
        self._lock = threading.Lock()

    def log_attempt(self, log: AttemptLog) -> None:
        evidence_json = json.dumps(log.evidence)
        failure_reason = log.failure_reason.value if log.failure_reason else None
        with self._lock:
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
        return self._rows_to_logs(rows)

    def get_attempts_by_task(self, task_id: str) -> list[AttemptLog]:
        """Return all attempt logs for a task, ordered by objective then attempt."""
        rows = self._conn.execute(
            "SELECT * FROM attempt_logs WHERE task_id=? ORDER BY objective_id, attempt_number",
            (task_id,),
        ).fetchall()
        return self._rows_to_logs(rows)

    def _rows_to_logs(self, rows: list) -> list[AttemptLog]:
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


class ObjectiveStateStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn: sqlite3.Connection = open_db(db_path)
        self._lock = threading.Lock()

    def upsert(
        self,
        task_id: str,
        objective_id: str,
        state: ObjectiveState,
        *,
        step_count: int = 0,
        token_count: int = 0,
        user_question: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO objective_states
                    (task_id, objective_id, state, step_count, token_count, user_question, failure_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, objective_id) DO UPDATE SET
                    state=excluded.state,
                    step_count=excluded.step_count,
                    token_count=excluded.token_count,
                    user_question=excluded.user_question,
                    failure_reason=excluded.failure_reason,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    task_id,
                    objective_id,
                    state.value,
                    step_count,
                    token_count,
                    user_question,
                    failure_reason,
                ),
            )
            self._conn.commit()

    def get(self, task_id: str, objective_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM objective_states WHERE task_id=? AND objective_id=?",
            (task_id, objective_id),
        ).fetchone()

    def mark_orphaned_running_as_interrupted(self) -> list[tuple[str, str]]:
        """Resolve any objective left at RUNNING/STUCK/STEERED by a prior crash.

        A bug or an unhandled exception in a code path added later could still
        leave a row stuck in one of these transient states forever with nothing
        ever checking it again — call once at orchestrator startup so state
        never silently stays inconsistent across a restart. Returns the
        (task_id, objective_id) pairs that were resolved.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_id, objective_id FROM objective_states WHERE state IN (?, ?, ?)",
                (ObjectiveState.RUNNING.value, ObjectiveState.STUCK.value, ObjectiveState.STEERED.value),
            ).fetchall()
            pairs = [(row["task_id"], row["objective_id"]) for row in rows]
            if pairs:
                self._conn.executemany(
                    """
                    UPDATE objective_states
                    SET state=?, failure_reason=?, updated_at=CURRENT_TIMESTAMP
                    WHERE task_id=? AND objective_id=?
                    """,
                    [
                        (ObjectiveState.FAILED.value, "interrupted_by_restart", task_id, objective_id)
                        for task_id, objective_id in pairs
                    ],
                )
                self._conn.commit()
            return pairs

    def list_by_task(self, task_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM objective_states WHERE task_id=? ORDER BY updated_at, objective_id",
            (task_id,),
        ).fetchall()

    def close(self) -> None:
        self._conn.close()
