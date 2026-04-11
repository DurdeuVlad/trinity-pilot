"""Terminal-friendly command surface for the running unified desktop app."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QMetaObject, Qt, Q_ARG

from mcp_server.live_test_cases import LiveTestCaseLibrary
from orchestrator.database import canonical_task_status


COMMAND_PIPE_AUTHKEY = b"orchestrator-command"
COMMAND_PIPE_NAME = "orchestrator-command-surface"
COMMAND_RESPONSE_TIMEOUT_SECONDS = 20.0
APP_START_TIMEOUT_SECONDS = 30.0
APP_WARMUP_GRACE_SECONDS = 3.0
_DESKTOP_APP_START_LOCK = threading.Lock()


class CommandSurfaceUnavailable(Exception):
    """Raised when the desktop app command surface is unavailable."""


def get_command_pipe_address() -> str:
    if os.name == "nt":
        return rf"\\.\pipe\{COMMAND_PIPE_NAME}"
    return str(Path("_runtime") / f"{COMMAND_PIPE_NAME}.sock")


def get_command_pipe_family() -> str:
    return "AF_PIPE" if os.name == "nt" else "AF_UNIX"


def send_command_via_pipe(
    command: str,
    *,
    args: dict[str, Any] | None = None,
    timeout_seconds: float = COMMAND_RESPONSE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send one command to the running desktop app."""
    payload = {
        "command": command,
        "args": args or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = Client(get_command_pipe_address(), family=get_command_pipe_family(), authkey=COMMAND_PIPE_AUTHKEY)
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            last_error = exc
            time.sleep(0.1)
    else:
        raise CommandSurfaceUnavailable(str(last_error) if last_error else "command pipe unavailable")

    with conn:
        conn.send(payload)
        remaining = max(0.1, deadline - time.monotonic())
        if not conn.poll(remaining):
            raise CommandSurfaceUnavailable("command surface timed out")
        response = conn.recv()
        if not isinstance(response, dict):
            raise CommandSurfaceUnavailable("invalid command response payload")
        return response


def ensure_desktop_app_started(
    *,
    startup_timeout_seconds: float = APP_START_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Launch the desktop app if needed and wait for the command surface."""
    with _DESKTOP_APP_START_LOCK:
        ready_response = _wait_for_command_surface(timeout_seconds=1.0)
        if ready_response is not None:
            return {
                "launched": False,
                "status": ready_response.get("status") or "already_running",
                "message": ready_response.get("message") or "desktop app command surface ready",
                "payload": ready_response.get("payload", {}),
            }

        ready_response = _wait_for_command_surface(timeout_seconds=APP_WARMUP_GRACE_SECONDS)
        if ready_response is not None:
            return {
                "launched": False,
                "status": ready_response.get("status") or "already_running",
                "message": ready_response.get("message") or "desktop app command surface ready",
                "payload": ready_response.get("payload", {}),
            }

        app_root = Path(__file__).resolve().parent.parent
        popen_kwargs: dict[str, Any] = {
            "cwd": str(app_root),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen([sys.executable, "main.py"], **popen_kwargs)

        deadline = time.monotonic() + startup_timeout_seconds
        last_error: Exception | None = None
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise CommandSurfaceUnavailable(
                        f"desktop app exited before command surface was ready (exit code {process.returncode})"
                    )
                try:
                    response = send_command_via_pipe("start-ui", timeout_seconds=1.0)
                    return {
                        "launched": True,
                        "status": "started",
                        "message": response.get("message") or "desktop app started",
                        "pid": process.pid,
                        "payload": response.get("payload", {}),
                    }
                except CommandSurfaceUnavailable as exc:
                    last_error = exc
                    time.sleep(0.2)
        except Exception:
            _terminate_started_process(process)
            raise

        _terminate_started_process(process)
        raise CommandSurfaceUnavailable(
            str(last_error) if last_error else "desktop app did not expose command surface in time"
        )


def _wait_for_command_surface(timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return send_command_via_pipe("start-ui", timeout_seconds=0.5)
        except CommandSurfaceUnavailable:
            time.sleep(0.1)
    return None


def _terminate_started_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            process.terminate()
            process.wait(timeout=5.0)
    except Exception:
        try:
            process.kill()
        except Exception:
            return


class AppCommandPipeServer:
    """GUI-side command surface exposed over a local pipe."""

    def __init__(
        self,
        *,
        event_bus: Any,
        history_manager: Any,
        run_monitor: Any,
        can_submit: Any,
        can_reset: Any,
        resume_run: Any,
        cancel_run: Any,
        reset_session: Any,
        shutdown_app: Any,
        case_library: LiveTestCaseLibrary | None = None,
        observe_timeout_seconds: float = 20.0,
    ) -> None:
        self._event_bus = event_bus
        self._history_manager = history_manager
        self._run_monitor = run_monitor
        self._can_submit = can_submit
        self._can_reset = can_reset
        self._resume_run = resume_run
        self._cancel_run = cancel_run
        self._reset_session = reset_session
        self._shutdown_app = shutdown_app
        self._case_library = case_library or LiveTestCaseLibrary()
        self._observe_timeout_seconds = observe_timeout_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._request_to_task: dict[str, str] = {}
        if hasattr(self._event_bus, "pipe_task_registered"):
            self._event_bus.pipe_task_registered.connect(self._on_pipe_task_registered)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._poke()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poke(self) -> None:
        try:
            conn = Client(get_command_pipe_address(), family=get_command_pipe_family(), authkey=COMMAND_PIPE_AUTHKEY)
            with conn:
                conn.send({"command": "__poke__", "args": {}})
        except Exception:
            pass

    def _serve(self) -> None:
        listener = Listener(get_command_pipe_address(), family=get_command_pipe_family(), authkey=COMMAND_PIPE_AUTHKEY)
        try:
            while not self._stop_event.is_set():
                conn = listener.accept()
                with conn:
                    try:
                        payload = conn.recv()
                        response = self._handle_payload(payload)
                    except Exception as exc:
                        response = self._error("internal_error", str(exc), command="unknown")
                    try:
                        conn.send(json.loads(json.dumps(response, default=str)))
                    except (BrokenPipeError, OSError):
                        continue
        finally:
            listener.close()

    def _handle_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._error("invalid_payload", "payload must be an object")
        command = str(payload.get("command", "")).strip()
        args = payload.get("args") or {}
        if command == "__poke__":
            return self._ok(command, {"message": "noop"})
        if command == "start-ui":
            return self._ok(command, {"message": "desktop app command surface ready"})
        if command == "list-cases":
            return self._ok(command, {"cases": self._case_library.list_cases()})
        if command == "submit-case":
            return self._submit_case(command, args)
        if command == "submit-task":
            return self._submit_task(command, args)
        if command == "get-run-status":
            return self._get_run_status(command, args)
        if command == "list-runs":
            limit = int(args.get("limit", 20))
            return self._ok(command, {"runs": self._history_manager.list_tasks(limit=limit)})
        if command == "stream-events":
            return self._stream_events(command, args)
        if command == "get-artifact-bundle":
            return self._get_artifact_bundle(command, args)
        if command == "approve-intervention":
            return self._approve_intervention(command, args)
        if command == "terminate-run":
            return self._terminate_run(command, args)
        if command == "reset-session":
            return self._reset_session_state(command)
        if command == "shutdown-ui":
            return self._shutdown_ui(command)
        if command == "tail-latest-run":
            return self._tail_latest_run(command, args)
        return self._error("unknown_command", f"Unknown command: {command}", command=command)

    def _submit_case(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        case_id = str(args.get("case_id") or args.get("path") or "").strip()
        if not case_id:
            return self._error("invalid_arg", "case_id or path is required", command=command)
        case = self._case_library.resolve_case(case_id)
        domain = LiveTestCaseLibrary.to_execution_domain(case.domain)
        result = self._dispatch_task(case.user_prompt, domain)
        payload = dict(result.get("payload", {}))
        payload["case"] = {
            "id": case.id,
            "title": case.title,
            "domain": case.domain,
            "path": case.path,
        }
        result["payload"] = payload
        return result

    def _submit_task(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        description = str(args.get("description", "")).strip()
        if not description:
            return self._error("invalid_arg", "description is required", command=command)
        domain = str(args.get("domain", "mixed")).strip() or "mixed"
        return self._dispatch_task(description, domain)

    def _dispatch_task(self, description: str, domain: str) -> dict[str, Any]:
        block_reason = self._can_submit()
        if block_reason is not None:
            return self._error("submission_blocked", block_reason, command="submit")
        request_id = f"cmd-{uuid.uuid4().hex[:16]}"
        signal = getattr(self._event_bus, "pipe_task_submitted", None)
        invoked = False
        try:
            invoked = bool(
                QMetaObject.invokeMethod(
                    self._event_bus,
                    "submit_task_request_from_pipe",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, description),
                    Q_ARG(str, domain),
                    Q_ARG(str, request_id),
                )
            )
        except TypeError:
            invoked = False
        if not invoked and signal is not None and hasattr(signal, "emit"):
            signal.emit(description, domain, request_id)
            invoked = True
        if not invoked:
            return self._error("submission_failed", "task submission could not be dispatched", command="submit")
        task = self._wait_for_task(request_id=request_id)
        if task is None:
            return self._error("task_not_observed", "task accepted but no history row was observed", command="submit")
        return self._ok(
            "submit",
            {
                "task_id": task.get("task_id"),
                "description": task.get("description"),
                "domain": task.get("domain"),
                "status": task.get("status"),
            },
            status=task.get("status", "submitted"),
            task_id=task.get("task_id"),
        )

    def _get_run_status(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        task_id = self._resolve_task_id(str(args.get("task_id", "latest")))
        if not task_id:
            return self._error("not_found", "no matching run found", command=command)
        task = self._history_manager.get_task_with_steps(task_id)
        if task is None:
            return self._error("not_found", f"run not found: {task_id}", command=command)
        task_payload, steps = self._split_task_details(task)
        after_sequence = int(args.get("after_sequence", 0))
        return self._ok(
            command,
            {
                "task": task_payload,
                "steps": steps,
                "latest_events": self._run_monitor.get_events(task_id, after_sequence=after_sequence),
            },
            status=task_payload.get("status", "unknown"),
            task_id=task_id,
        )

    def _stream_events(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        task_id = self._resolve_task_id(str(args.get("task_id", "latest")))
        if not task_id:
            return self._error("not_found", "no matching run found", command=command)
        after_sequence = int(args.get("after_sequence", 0))
        limit = int(args.get("limit", 200))
        events = self._run_monitor.get_events(task_id, after_sequence=after_sequence, limit=limit)
        return self._ok(command, {"task_id": task_id, "events": events}, task_id=task_id)

    def _get_artifact_bundle(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        task_id = self._resolve_task_id(str(args.get("task_id", "latest")))
        if not task_id:
            return self._error("not_found", "no matching run found", command=command)
        bundle = self._run_monitor.build_artifact_bundle(task_id)
        return self._ok(
            command,
            bundle,
            task_id=task_id,
            status=bundle["final_disposition"]["task_status"],
        )

    def _approve_intervention(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        self._resume_run()
        task_id = self._resolve_task_id(str(args.get("task_id", "latest")))
        if task_id:
            self._run_monitor.record_event(
                "intervention_approved",
                {"message": "Intervention approved from command surface"},
                task_id=task_id,
                status="running",
            )
        return self._ok(command, {"task_id": task_id}, task_id=task_id)

    def _terminate_run(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        task_id = self._resolve_task_id(str(args.get("task_id", "latest")))
        reason = str(args.get("reason", "terminated from command surface")).strip()
        self._cancel_run(reason)
        terminal_task = self._wait_for_terminal_task(task_id) if task_id else None
        canonical_status = canonical_task_status(terminal_task) if terminal_task else "policy_terminated"
        if task_id:
            self._run_monitor.record_event(
                "policy_stop",
                {"reason": reason},
                task_id=task_id,
                status="policy_terminated",
            )
        payload = {"task_id": task_id, "reason": reason}
        if terminal_task is not None:
            payload["task"] = terminal_task
        return self._ok(command, payload, task_id=task_id, status=canonical_status)

    def _tail_latest_run(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        task_id = self._resolve_task_id("latest")
        if not task_id:
            return self._error("not_found", "no runs found", command=command)
        after_sequence = int(args.get("after_sequence", 0))
        events = self._run_monitor.get_events(task_id, after_sequence=after_sequence)
        return self._ok(command, {"task_id": task_id, "events": events}, task_id=task_id)

    def _reset_session_state(self, command: str) -> dict[str, Any]:
        block_reason = self._can_reset()
        if block_reason is not None:
            return self._error("reset_blocked", block_reason, command=command)
        self._reset_session()
        return self._ok(command, {"message": "desktop app session reset for the next run"})

    def _shutdown_ui(self, command: str) -> dict[str, Any]:
        block_reason = self._can_reset()
        if block_reason is not None:
            return self._error("shutdown_blocked", block_reason, command=command)
        self._shutdown_app()
        return self._ok(command, {"message": "desktop app shutdown scheduled"})

    def _resolve_task_id(self, task_id: str) -> str | None:
        if task_id != "latest":
            return task_id
        return self._run_monitor.latest_task_id()

    def _wait_for_task(self, *, request_id: str) -> dict[str, Any] | None:
        deadline = time.monotonic() + self._observe_timeout_seconds
        while time.monotonic() < deadline:
            task_id = self._request_to_task.get(request_id)
            if task_id:
                task = self._load_task_summary(task_id)
                if task is not None:
                    return task
            time.sleep(0.1)
        return None

    def _wait_for_terminal_task(self, task_id: str, timeout_seconds: float | None = None) -> dict[str, Any] | None:
        deadline = time.monotonic() + (timeout_seconds or self._observe_timeout_seconds)
        while time.monotonic() < deadline:
            task = self._load_task_summary(task_id)
            if task is not None and canonical_task_status(task) not in {"pending", "running"}:
                return task
            time.sleep(0.1)
        return self._load_task_summary(task_id)

    def _on_pipe_task_registered(self, request_id: str, task_id: str) -> None:
        self._request_to_task[str(request_id)] = str(task_id)

    @staticmethod
    def _split_task_details(details: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        steps = list(details.get("steps", []))
        if "task" in details:
            return dict(details.get("task", {})), steps
        return ({key: value for key, value in details.items() if key != "steps"}, steps)

    def _load_task_summary(self, task_id: str) -> dict[str, Any] | None:
        details = self._history_manager.get_task_with_steps(task_id)
        if details is None:
            return None
        task, _steps = self._split_task_details(details)
        return task

    def _ok(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        status: str = "ok",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "command": command,
            "task_id": task_id,
            "status": status,
            "message": payload.get("message", ""),
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _error(self, error_code: str, message: str, *, command: str = "unknown") -> dict[str, Any]:
        return {
            "ok": False,
            "command": command,
            "task_id": None,
            "status": "error",
            "message": message,
            "error_code": error_code,
            "payload": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
