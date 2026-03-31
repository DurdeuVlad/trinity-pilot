"""Named-pipe transport for cross-process task submission.

This module lets an external MCP process submit tasks to a running GUI process
without relying on in-process Qt signals.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from multiprocessing.connection import Client, Listener
from pathlib import Path
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QMetaObject, Qt, Q_ARG


PIPE_AUTHKEY = b"orchestrator-mcp"
PIPE_NAME = "orchestrator-task-submit"
_TRANSIENT_SUBMISSION_BLOCK = "Task is already running."
_TRANSIENT_BLOCK_WAIT_SECONDS = 1.5
_MAX_REQUEST_CACHE_SIZE = 256


class PipeSubmissionUnavailable(Exception):
    """Raised when the named-pipe endpoint is unavailable."""


def get_pipe_address() -> str:
    """Return platform-specific pipe address."""
    if os.name == "nt":
        return rf"\\.\pipe\{PIPE_NAME}"
    return str(Path("_runtime") / f"{PIPE_NAME}.sock")


def get_pipe_family() -> str:
    """Return multiprocessing connection family for current platform."""
    return "AF_PIPE" if os.name == "nt" else "AF_UNIX"


def submit_task_via_pipe(
    *,
    description: str,
    domain: str,
    timeout_seconds: float = 5.0,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Submit a task over named pipe and wait for listener response."""
    payload = {
        "request_id": request_id or f"mcp-{uuid.uuid4().hex[:16]}",
        "description": description,
        "domain": domain,
        "observe_timeout_seconds": timeout_seconds,
    }
    address = get_pipe_address()
    family = get_pipe_family()

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            conn = Client(address, family=family, authkey=PIPE_AUTHKEY)
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            last_error = exc
            time.sleep(0.1)
    else:
        raise PipeSubmissionUnavailable(str(last_error) if last_error else "pipe endpoint unavailable")

    with conn:
        conn.send(payload)
        remaining = max(0.1, (deadline - time.monotonic()) + 0.5)
        if not conn.poll(remaining):
            raise PipeSubmissionUnavailable("pipe response timeout")
        response = conn.recv()
        if not isinstance(response, dict):
            raise PipeSubmissionUnavailable("invalid response payload")
        return response


class TaskSubmissionPipeServer:
    """GUI-side named-pipe listener that forwards tasks into EventBus."""

    def __init__(
        self,
        *,
        event_bus: Any,
        history_manager: Any,
        can_submit: Callable[[], str | None] | None = None,
        observe_timeout_seconds: float = 20.0,
    ):
        self._event_bus = event_bus
        self._history_manager = history_manager
        self._can_submit = can_submit
        self._observe_timeout_seconds = observe_timeout_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._request_cache: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        """Start listener thread if not already running."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listener thread and unblock accept loop."""
        self._stop_event.set()
        self._poke()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poke(self) -> None:
        """Wake listener accept() call so shutdown can proceed."""
        try:
            conn = Client(get_pipe_address(), family=get_pipe_family(), authkey=PIPE_AUTHKEY)
            with conn:
                conn.send({"request_id": "shutdown-poke", "description": "", "domain": ""})
        except Exception:
            pass

    def _serve(self) -> None:
        """Blocking accept loop for named-pipe submissions."""
        listener = Listener(get_pipe_address(), family=get_pipe_family(), authkey=PIPE_AUTHKEY)
        try:
            while not self._stop_event.is_set():
                conn = listener.accept()
                with conn:
                    try:
                        payload = conn.recv()
                        response = self._handle_payload(payload)
                    except Exception as exc:
                        response = {
                            "ok": False,
                            "error_code": "pipe_server_error",
                            "message": f"pipe listener error: {exc}",
                        }
                    try:
                        conn.send(response)
                    except (BrokenPipeError, OSError):
                        # Client may timeout or close early; keep listener alive.
                        continue
        finally:
            listener.close()

    def _handle_payload(self, payload: Any) -> dict[str, Any]:
        """Validate request and dispatch a task via EventBus."""
        if self._stop_event.is_set():
            return {"ok": False, "error_code": "stopping", "message": "listener stopping"}

        if not isinstance(payload, dict):
            return {"ok": False, "error_code": "invalid_payload", "message": "payload must be an object"}

        request_id = str(payload.get("request_id", "")).strip()
        description = str(payload.get("description", "")).strip()
        domain = str(payload.get("domain", "")).strip()

        if request_id == "shutdown-poke":
            return {"ok": False, "error_code": "noop", "message": "listener poke"}

        if not request_id or not description or not domain:
            return {
                "ok": False,
                "error_code": "invalid_payload",
                "message": "request_id, description, and domain are required",
            }

        if request_id in self._request_cache:
            return self._request_cache[request_id]

        if self._can_submit is not None:
            block_reason = self._wait_for_submission_slot()
            if block_reason is not None:
                response = {
                    "ok": False,
                    "error_code": "submission_blocked",
                    "message": block_reason,
                    "description": description,
                    "domain": domain,
                }
                self._cache_response(request_id, response)
                return response

        submitted_at = time.time()
        invoked = self._dispatch_task_submission(description, domain)
        if not invoked:
            response = {
                "ok": False,
                "error_code": "submission_dispatch_failed",
                "message": "Task submission could not be dispatched onto the app thread.",
                "description": description,
                "domain": domain,
            }
            self._cache_response(request_id, response)
            return response
        observe_timeout = payload.get("observe_timeout_seconds", self._observe_timeout_seconds)
        try:
            observe_timeout = float(observe_timeout)
        except (TypeError, ValueError):
            observe_timeout = self._observe_timeout_seconds
        observe_timeout = max(0.2, min(observe_timeout, self._observe_timeout_seconds))

        task = self._wait_for_task(
            description=description,
            domain=domain,
            submitted_at=submitted_at,
            timeout_seconds=observe_timeout,
        )

        if task is None:
            response = {
                "ok": False,
                "error_code": "task_not_observed",
                "message": "Task dispatch was accepted but no persisted task record was observed.",
                "description": description,
                "domain": domain,
            }
        else:
            response = {
                "ok": True,
                "task_id": task["task_id"],
                "description": task.get("description", description),
                "domain": task.get("domain", domain),
                "status": task.get("status", "submitted"),
            }

        self._cache_response(request_id, response)
        return response

    def _dispatch_task_submission(self, description: str, domain: str) -> bool:
        """Queue submission onto the app thread, with a test-friendly direct fallback."""
        try:
            invoked = bool(
                QMetaObject.invokeMethod(
                    self._event_bus,
                    "submit_task_from_pipe",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, description),
                    Q_ARG(str, domain),
                )
            )
            if invoked:
                return True
        except TypeError:
            pass

        try:
            signal = getattr(self._event_bus, "task_submitted", None)
            if signal is None or not hasattr(signal, "emit"):
                return False
            signal.emit(description, domain)
            return True
        except Exception:
            return False

    def _cache_response(self, request_id: str, response: dict[str, Any]) -> None:
        """Store an idempotent response while keeping memory bounded."""
        self._request_cache[request_id] = response
        if len(self._request_cache) <= _MAX_REQUEST_CACHE_SIZE:
            return
        oldest_request_id = next(iter(self._request_cache))
        if oldest_request_id != request_id:
            self._request_cache.pop(oldest_request_id, None)

    def _wait_for_submission_slot(self) -> str | None:
        """Allow brief worker-teardown races to clear before rejecting a submit."""
        if self._can_submit is None:
            return None

        block_reason = self._can_submit()
        if block_reason is None or block_reason != _TRANSIENT_SUBMISSION_BLOCK:
            return block_reason

        deadline = time.monotonic() + min(self._observe_timeout_seconds, _TRANSIENT_BLOCK_WAIT_SECONDS)
        while time.monotonic() < deadline:
            time.sleep(0.05)
            block_reason = self._can_submit()
            if block_reason is None:
                return None
            if block_reason != _TRANSIENT_SUBMISSION_BLOCK:
                return block_reason
        return block_reason

    def _wait_for_task(
        self,
        *,
        description: str,
        domain: str,
        submitted_at: float,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Wait for an observed task row that matches this request."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            recent_tasks = self._history_manager.list_tasks(limit=20)
            for task in recent_tasks:
                if task.get("description") != description:
                    continue
                if task.get("domain") != domain:
                    continue
                created_at = str(task.get("created_at") or "")
                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at)
                        if created_dt.tzinfo is None:
                            # History rows are stored as UTC-naive ISO timestamps.
                            created_dt = created_dt.replace(tzinfo=timezone.utc)
                        created_ts = created_dt.timestamp()
                    except ValueError:
                        created_ts = submitted_at
                    if created_ts + 1.0 < submitted_at:
                        continue
                return task
            time.sleep(0.1)
        return None
