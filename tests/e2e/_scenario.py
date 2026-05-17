"""E2EScenario dataclass and BridgeTestHarness for e2e tests."""
from __future__ import annotations

import asyncio
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from trinity_pilot.config import Settings
from trinity_pilot.memory.store import TaskStore
from trinity_pilot.ui.bridge import WorkflowBridge


@dataclass
class E2EScenario:
    """Definition of a single end-to-end test scenario."""

    task: str
    domain: str  # "terminal" | "browser" | "desktop"
    setup_fn: Callable[[], None] | None = None
    teardown_fn: Callable[[], None] | None = None
    expected_status: str = "completed"
    expected_files: list[Path] = field(default_factory=list)
    expected_signals: list[type] = field(default_factory=list)
    canned_answers: dict[str, str] = field(default_factory=dict)
    timeout_sec: int = 120
    tags: list[str] = field(default_factory=list)


class BridgeTestHarness:
    """Wraps WorkflowBridge for e2e testing via threading.Event synchronization.

    Usage:
        harness = BridgeTestHarness(settings, db_path)
        task_id = harness.submit(task_text, objectives_dicts)
        done = harness.wait_for_completion(timeout=120)
        result = harness.last_result
        status = harness.get_db_status(task_id)
        signals = harness.drain_signals()
    """

    def __init__(
        self,
        settings: Settings,
        db_path: str,
        signals_queue: asyncio.Queue | None = None,
    ) -> None:
        self._settings = settings
        self._db_path = db_path
        self._signals_queue: asyncio.Queue = signals_queue or asyncio.Queue()
        self._done_event = threading.Event()
        self._last_result: dict[str, Any] | None = None
        self._log_lines: list[str] = []
        self._task_id: str | None = None
        self._bridge = WorkflowBridge(settings, db_path=db_path)

    def submit(
        self,
        task: str,
        objectives: list[dict] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> str:
        """Submit a task to the bridge and return the task_id."""
        self._done_event.clear()
        self._last_result = None
        self._log_lines = []

        def _on_log(msg: str) -> None:
            self._log_lines.append(msg)
            if on_log:
                on_log(msg)

        def _on_done(result: dict[str, Any]) -> None:
            self._last_result = result
            self._done_event.set()

        task_id = self._bridge.start_task(
            user_request=task,
            on_log=_on_log,
            on_done=_on_done,
            objectives=objectives,
            signals_queue=self._signals_queue,
        )
        self._task_id = task_id
        return task_id

    def wait_for_completion(self, timeout: float = 120.0) -> bool:
        """Block until task completes or timeout elapses. Returns True if done, False on timeout."""
        return self._done_event.wait(timeout=timeout)

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    @property
    def log_lines(self) -> list[str]:
        return list(self._log_lines)

    def write_log(self, path: Path) -> None:
        """Write captured log lines to a file (even if run failed)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for line in self._log_lines:
                f.write(line + "\n")

    def drain_signals(self) -> list[Any]:
        """Drain all signals currently in the queue and return them as a list."""
        signals: list[Any] = []
        while True:
            try:
                signals.append(self._signals_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return signals

    def get_db_status(self, task_id: str) -> str | None:
        """Return the task status string from the DB, or None if not found."""
        store = TaskStore(self._db_path)
        record = store.get_task(task_id)
        return record.status.value if record else None

    def dispose(self) -> None:
        """Stop any running worker."""
        try:
            self._bridge.stop_task()
        except Exception:
            pass
