"""FastMCP stdio server exposing task orchestration control surface.

Run: python -m trinity_pilot.mcp.orchestrator_server
Exposes: submit_task, get_task_status, cancel_task, list_tasks,
         get_task_events, reset_session, get_artifact_bundle
"""
from __future__ import annotations

import json
import logging
import sys
import uuid

from fastmcp import FastMCP

from trinity_pilot.config import ConfigError, Settings
from trinity_pilot.core.types import TaskStatus
from trinity_pilot.memory.store import AttemptStore, TaskStore
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings — fail fast if env is misconfigured
# ---------------------------------------------------------------------------
try:
    _settings = Settings.from_env()
except ConfigError as _e:
    _logger.error("Configuration error: %s", _e)
    sys.exit(1)

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="trinity-pilot-orchestrator",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("health://orchestrator")
def health() -> str:
    return "ok"


@mcp.resource("version://orchestrator")
def version() -> str:
    return "0.1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_stores() -> tuple[TaskStore, AttemptStore]:
    """Return (TaskStore, AttemptStore) both pointed at settings.db_path."""
    return TaskStore(_settings.db_path), AttemptStore(_settings.db_path)


def _error(error_code: str, message: str, task_id: str | None = None) -> dict:
    result: dict = {"error_code": error_code, "message": message}
    if task_id is not None:
        result["task_id"] = task_id
    return result


_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
_RUNNING: dict[str, AsyncTaskOrchestrator] = {}

# ---------------------------------------------------------------------------
# Story 2: submit_task
# ---------------------------------------------------------------------------


@mcp.tool()
async def submit_task(user_request: str, task_id: str | None = None) -> dict:
    """Submit a task to the orchestration engine and block until it completes.

    Runs synchronously within the MCP call so the subprocess stays alive for
    the full duration of the task.  The caller (app_control_cli) can simply
    wait for this tool to return rather than polling stream-events separately.
    """
    if task_id is None:
        task_id = str(uuid.uuid4())

    try:
        orchestrator = AsyncTaskOrchestrator(_settings)
        _RUNNING[task_id] = orchestrator
        try:
            result = await orchestrator.run(user_request, task_id=task_id)
        finally:
            _RUNNING.pop(task_id, None)
    except Exception as exc:
        return _error(
            "TASK_FAILED",
            f"Task execution failed: {exc}",
            task_id,
        )

    return result


# ---------------------------------------------------------------------------
# Story 3: get_task_status
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """Get current status of a task from SQLite and objective state rows."""

    task_store, attempt_store = _get_stores()
    task = task_store.get_task(task_id)
    if task is None:
        return _error("TASK_NOT_FOUND", f"No task with id={task_id}", task_id)

    current_objective: str | None = None
    completed_objectives: list[str] = []
    last_attempt_status: str | None = None
    if orchestrator := _RUNNING.get(task_id):
        snapshot = orchestrator.snapshot
        current_objective = snapshot.current_objective
        completed_objectives = snapshot.completed_objectives

    # Latest attempt status from SQLite
    try:
        attempts = attempt_store.get_attempts_by_task(task_id)
        if attempts:
            last_attempt_status = attempts[-1].status
    except Exception:
        _logger.exception("Unable to load attempts for task %s", task_id)

    return {
        "task_id": task_id,
        "status": task.status.value,
        "current_objective": current_objective,
        "completed_objectives": completed_objectives,
        "last_attempt_status": last_attempt_status,
    }


# ---------------------------------------------------------------------------
# Story 4: cancel_task
# ---------------------------------------------------------------------------


@mcp.tool()
async def cancel_task(task_id: str) -> dict:
    """Cancel a running task by updating SQLite state."""

    task_store, _ = _get_stores()
    task = task_store.get_task(task_id)
    if task is None:
        return _error("TASK_NOT_FOUND", f"No task with id={task_id}", task_id)

    if task.status in _TERMINAL_STATUSES:
        return _error(
            "ALREADY_TERMINAL",
            f"Task {task_id} is already in terminal state: {task.status.value}",
            task_id,
        )

    if orchestrator := _RUNNING.get(task_id):
        orchestrator.cancel()
    task_store.update_status(task_id, TaskStatus.CANCELLED)

    return {"task_id": task_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Story 5: list_tasks
# ---------------------------------------------------------------------------


@mcp.tool()
def list_tasks(status_filter: str | None = None) -> dict:
    """List all tasks, optionally filtered by status."""
    status_enum: TaskStatus | None = None
    if status_filter is not None:
        valid_values = {s.value for s in TaskStatus}
        if status_filter not in valid_values:
            return _error(
                "INVALID_STATUS",
                f"Invalid status_filter '{status_filter}'. Valid values: {sorted(valid_values)}",
            )
        status_enum = TaskStatus(status_filter)

    task_store, _ = _get_stores()
    tasks = task_store.list_tasks(status=status_enum)

    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "user_request": t.user_request,
                "status": t.status.value,
                "objective_count": len(t.objectives),
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


# ---------------------------------------------------------------------------
# Story 6: get_task_events
# ---------------------------------------------------------------------------


@mcp.tool()
def get_task_events(task_id: str, since_cursor: str | None = None) -> dict:
    """Poll attempt_logs for new events since a cursor (ISO-8601 created_at timestamp).

    Returns events batch, next_cursor, and whether the task has reached a terminal state.
    """
    task_store, _ = _get_stores()
    task = task_store.get_task(task_id)
    if task is None:
        return _error("TASK_NOT_FOUND", f"No task with id={task_id}", task_id)

    effective_cursor = since_cursor if since_cursor is not None else "1970-01-01T00:00:00"

    # Direct SQLite query using the shared connection path
    from trinity_pilot.memory.db import open_db

    conn = open_db(_settings.db_path)
    try:
        rows = conn.execute(
            """
            SELECT attempt_id, task_id, objective_id, attempt_number,
                   status, failure_reason, evidence_json, created_at
            FROM attempt_logs
            WHERE task_id=? AND created_at > ?
            ORDER BY created_at ASC
            """,
            (task_id, effective_cursor),
        ).fetchall()
    finally:
        conn.close()

    events = []
    for row in rows:
        try:
            evidence = json.loads(row["evidence_json"])
        except (json.JSONDecodeError, TypeError):
            evidence = {}

        evidence_summary = {
            "passed": evidence.get("passed"),
            "screenshot_path": evidence.get("screenshot_path"),
            "notes": evidence.get("notes"),
            "recovery_hint": evidence.get("recovery_hint"),
            "failure_reason": evidence.get("failure_reason"),
        }

        events.append(
            {
                "attempt_id": row["attempt_id"],
                "objective_id": row["objective_id"],
                "attempt_number": row["attempt_number"],
                "status": row["status"],
                "failure_reason": row["failure_reason"],
                "evidence_summary": evidence_summary,
                "created_at": row["created_at"],
            }
        )

    next_cursor = events[-1]["created_at"] if events else effective_cursor
    is_terminal = task.status in _TERMINAL_STATUSES

    return {
        "task_id": task_id,
        "task_status": task.status.value,
        "events": events,
        "next_cursor": next_cursor,
        "is_terminal": is_terminal,
    }


# ---------------------------------------------------------------------------
# Story 7: reset_session
# ---------------------------------------------------------------------------


@mcp.tool()
async def reset_session(confirm: bool = False) -> dict:
    """Reset all session data (tasks, attempts, reflections).

    If confirm=False, returns a dry-run summary.
    If confirm=True, cancels running local tasks and deletes all SQLite session rows.
    """
    from trinity_pilot.memory.db import open_db

    conn = open_db(_settings.db_path)
    try:
        tasks_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        attempts_count = conn.execute("SELECT COUNT(*) FROM attempt_logs").fetchone()[0]
    finally:
        conn.close()

    if not confirm:
        return {
            "dry_run": True,
            "tasks_count": tasks_count,
            "attempts_count": attempts_count,
            "message": "Call with confirm=true to delete.",
        }

    warnings: list[str] = []
    for orchestrator in list(_RUNNING.values()):
        orchestrator.cancel()
    _RUNNING.clear()

    # Delete all rows from SQLite
    conn = open_db(_settings.db_path)
    try:
        conn.execute("DELETE FROM attempt_logs")
        conn.execute("DELETE FROM reflections")
        conn.execute("DELETE FROM objective_states")
        conn.execute("DELETE FROM tasks")
        conn.commit()
        deleted_tasks = tasks_count
        deleted_attempts = attempts_count
    except Exception as exc:
        conn.rollback()
        return _error("DB_DELETE_FAILED", f"SQLite DELETE raised: {exc}")
    finally:
        conn.close()

    result: dict = {
        "dry_run": False,
        "deleted_tasks": deleted_tasks,
        "deleted_attempts": deleted_attempts,
        "status": "reset",
    }
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Story 8: get_artifact_bundle
# ---------------------------------------------------------------------------


@mcp.tool()
def get_artifact_bundle(task_id: str) -> dict:
    """Return the full artifact bundle for a completed task.

    Includes task metadata, summary stats, and all attempt evidence (untruncated).
    """
    task_store, attempt_store = _get_stores()
    task = task_store.get_task(task_id)
    if task is None:
        return _error("TASK_NOT_FOUND", f"No task with id={task_id}", task_id)

    attempts = attempt_store.get_attempts_by_task(task_id)
    if not attempts:
        return _error(
            "NO_ATTEMPTS_YET",
            f"Task {task_id} exists but has no attempt logs yet (still planning or pending).",
            task_id,
        )

    # Aggregate by objective_id: keep only the last attempt per objective.
    last_attempt: dict = {}
    for a in attempts:
        if a.objective_id not in last_attempt or a.attempt_number > last_attempt[a.objective_id].attempt_number:
            last_attempt[a.objective_id] = a
    passed_count = sum(1 for a in last_attempt.values() if a.status == "passed")
    failed_count = sum(1 for a in last_attempt.values() if a.status == "failed")
    overall_passed = task.status == TaskStatus.COMPLETED and failed_count == 0

    attempt_dicts = []
    for a in attempts:
        attempt_dicts.append(
            {
                "attempt_id": a.attempt_id,
                "objective_id": a.objective_id,
                "attempt_number": a.attempt_number,
                "status": a.status,
                "failure_reason": a.failure_reason.value if a.failure_reason else None,
                "evidence": a.evidence,
            }
        )

    return {
        "task_id": task_id,
        "user_request": task.user_request,
        "status": task.status.value,
        "summary": {
            "total_objectives": len(last_attempt),
            "passed": passed_count,
            "failed": failed_count,
            "overall_passed": overall_passed,
        },
        "attempts": attempt_dicts,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
