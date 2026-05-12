"""FastMCP stdio server exposing task orchestration control surface.

Run: python -m trinity_pilot.mcp.orchestrator_server
Exposes: submit_task, get_task_status, cancel_task, list_tasks,
         get_task_events, reset_session, get_artifact_bundle
"""
from __future__ import annotations

import json
import socket
import sys
import uuid
from datetime import timedelta

from fastmcp import FastMCP

from trinity_pilot.config import ConfigError, Settings
from trinity_pilot.core.types import TaskRecord, TaskStatus
from trinity_pilot.memory.store import AttemptStore, TaskStore

# ---------------------------------------------------------------------------
# Settings — fail fast if env is misconfigured
# ---------------------------------------------------------------------------
try:
    _settings = Settings.from_env()
except ConfigError as _e:
    print(f"[orchestrator_server] Configuration error: {_e}", file=sys.stderr)
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


def _temporal_reachable(host: str) -> bool:
    """Return True if the Temporal gRPC port is open."""
    try:
        addr, port_str = host.rsplit(":", 1)
        with socket.create_connection((addr, int(port_str)), timeout=1):
            return True
    except OSError:
        return False


def _get_stores() -> tuple[TaskStore, AttemptStore]:
    """Return (TaskStore, AttemptStore) both pointed at settings.db_path."""
    return TaskStore(_settings.db_path), AttemptStore(_settings.db_path)


def _error(error_code: str, message: str, task_id: str | None = None) -> dict:
    result: dict = {"error_code": error_code, "message": message}
    if task_id is not None:
        result["task_id"] = task_id
    return result


_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

# ---------------------------------------------------------------------------
# Story 2: submit_task
# ---------------------------------------------------------------------------


@mcp.tool()
async def submit_task(user_request: str, task_id: str | None = None) -> dict:
    """Submit a new task to the Trinity Pilot workflow engine.

    Creates a TaskRecord in SQLite and starts a Temporal TaskWorkflow.
    Returns task_id and status="running" on success.
    """
    import temporalio.client

    if task_id is None:
        task_id = str(uuid.uuid4())

    if not _temporal_reachable(_settings.temporal_host):
        return _error(
            "TEMPORAL_NOT_REACHABLE",
            (
                f"Cannot reach Temporal at {_settings.temporal_host}. "
                "Start the Trinity Pilot UI (which launches Temporal) with: "
                "python app_control_cli.py start-ui"
            ),
            task_id,
        )

    # Start Temporal workflow
    try:
        client = await temporalio.client.Client.connect(
            _settings.temporal_host, namespace=_settings.temporal_namespace
        )
        await client.start_workflow(
            "TaskWorkflow",
            user_request,
            id=task_id,
            task_queue="trinity-pilot",
            execution_timeout=timedelta(minutes=30),
        )
    except Exception as exc:
        return _error(
            "WORKFLOW_START_FAILED",
            f"Temporal start_workflow raised: {exc}",
            task_id,
        )

    # Persist in SQLite
    try:
        task_store, _ = _get_stores()
        task_store.save_task(
            TaskRecord(
                task_id=task_id,
                user_request=user_request,
                objectives=[],
                status=TaskStatus.RUNNING,
            )
        )
    except Exception as exc:
        return _error(
            "DB_WRITE_FAILED",
            f"Workflow started but SQLite write failed: {exc}",
            task_id,
        )

    return {
        "task_id": task_id,
        "status": "running",
        "temporal_host": _settings.temporal_host,
    }


# ---------------------------------------------------------------------------
# Story 3: get_task_status
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """Get current status of a task, combining SQLite and live Temporal queries."""
    import temporalio.client
    from temporalio.exceptions import WorkflowAlreadyStartedError

    task_store, attempt_store = _get_stores()
    task = task_store.get_task(task_id)
    if task is None:
        return _error("TASK_NOT_FOUND", f"No task with id={task_id}", task_id)

    current_objective: str | None = None
    completed_objectives: list[str] = []
    last_attempt_status: str | None = None

    # Query Temporal for live context (best-effort)
    if _temporal_reachable(_settings.temporal_host):
        try:
            client = await temporalio.client.Client.connect(
                _settings.temporal_host, namespace=_settings.temporal_namespace
            )
            handle = client.get_workflow_handle(task_id)
            current_objective = await handle.query("current_objective")
            completed_objectives = await handle.query("completed_objectives")
        except Exception:
            # Workflow is terminal or unreachable — leave as None/[]
            current_objective = None
            completed_objectives = []

    # Latest attempt status from SQLite
    try:
        attempts = attempt_store.get_attempts_by_task(task_id)
        if attempts:
            last_attempt_status = attempts[-1].status
    except Exception:
        pass

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
    """Cancel a running task by sending a cancel signal to Temporal and updating SQLite."""
    import temporalio.client

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

    if not _temporal_reachable(_settings.temporal_host):
        return _error(
            "TEMPORAL_NOT_REACHABLE",
            f"Cannot reach Temporal at {_settings.temporal_host}",
            task_id,
        )

    try:
        client = await temporalio.client.Client.connect(
            _settings.temporal_host, namespace=_settings.temporal_namespace
        )
        handle = client.get_workflow_handle(task_id)
        await handle.signal("cancel")
    except Exception as exc:
        return _error(
            "SIGNAL_FAILED",
            f"Temporal signal 'cancel' raised: {exc}",
            task_id,
        )

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
    If confirm=True, cancels running Temporal workflows and deletes all SQLite rows.
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

    # Cancel running Temporal workflows (best-effort)
    warnings: list[str] = []
    if _temporal_reachable(_settings.temporal_host):
        try:
            import temporalio.client

            client = await temporalio.client.Client.connect(
                _settings.temporal_host, namespace=_settings.temporal_namespace
            )
            async for wf in client.list_workflows(
                'TaskQueue="trinity-pilot" AND ExecutionStatus="Running"'
            ):
                try:
                    handle = client.get_workflow_handle(wf.id)
                    await handle.signal("cancel")
                except Exception as exc:
                    warnings.append(f"{wf.id}: {exc}")
        except Exception as exc:
            warnings.append(f"list_workflows failed: {exc}")

    # Delete all rows from SQLite
    conn = open_db(_settings.db_path)
    try:
        conn.execute("DELETE FROM attempt_logs")
        conn.execute("DELETE FROM reflections")
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

    passed_count = sum(1 for a in attempts if a.status == "passed")
    failed_count = sum(1 for a in attempts if a.status == "failed")
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
            "total_objectives": len(task.objectives) if task.objectives else len(attempts),
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
