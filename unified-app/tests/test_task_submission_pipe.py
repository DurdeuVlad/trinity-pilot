"""Regression tests for the cross-process task submission pipe."""
from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from mcp_server.task_submission_pipe import TaskSubmissionPipeServer


class _DummyHistoryManager:
    def __init__(self, task: dict[str, object]) -> None:
        self._task = task

    def list_tasks(self, limit: int = 20) -> list[dict[str, object]]:
        return [self._task]


class _DummyEventBus:
    pass


def test_wait_for_task_accepts_recent_naive_utc_timestamp():
    """Recent UTC-naive rows should not be rejected as stale in non-UTC locales."""
    recent_created_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    task = {
        "task_id": "run_live_demo",
        "description": "List all Python files in the current directory and count them",
        "domain": "cli",
        "created_at": recent_created_at,
        "status": "running",
    }
    server = TaskSubmissionPipeServer(
        event_bus=_DummyEventBus(),
        history_manager=_DummyHistoryManager(task),
    )

    observed = server._wait_for_task(
        description=task["description"],
        domain=task["domain"],
        submitted_at=datetime.now(timezone.utc).timestamp(),
        timeout_seconds=0.2,
    )

    assert observed == task
