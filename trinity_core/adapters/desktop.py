"""Desktop automation adapter."""

import asyncio
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from desktop_io_models import DesktopTaskResult

logger = logging.getLogger(__name__)

from ..adapter import TaskAdapter
from ..models import ExecutionLog, TaskInput, TaskResult, failure_code, is_retriable
from ..telemetry import (
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_SUCCEEDED,
    emit_event,
    make_event_payload,
)


DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS = 600.0
_FLIGHT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "unified-app" / "_runtime" / "flight_reports"
AUTH_TOKENS = ("api_key_invalid", "invalid api key", "api key not valid", "unauthenticated", "authentication failed")
USER_ERROR_TOKENS = ("clarify", "need assistance", "invalid objective", "unsafe request")

# ---------------------------------------------------------------------------
# Desktop session pool — one persistent subprocess per task run
# ---------------------------------------------------------------------------

_ACTIVE_DESKTOP_SESSIONS: dict[str, "DesktopSession"] = {}


class DesktopSession:
    """Wraps a long-running generic_backend.py --session-mode process.

    One instance is created per task run and reused for every desktop action
    within that run, so COM/UIA handles and any open app windows persist
    between consecutive calls instead of being torn down after each one.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            _resolve_backend_script(),
            "--session-mode",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_build_subprocess_env(),
        )

    async def run_task(self, payload: dict[str, Any], timeout: float) -> "DesktopTaskResult":
        async with self._lock:
            await self._ensure_started()
            assert self._process is not None
            line = json.dumps(payload) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            deadline = asyncio.get_running_loop().time() + timeout
            live_events: list[dict] = []
            text = ""
            try:
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    raw = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=remaining,
                    )
                    text = raw.decode().strip()
                    if not text:
                        raise ValueError("Desktop session returned empty response")
                    if text.startswith("[EVT]"):
                        try:
                            live_events.append(json.loads(text[5:]))
                        except Exception:
                            pass
                        continue
                    break
                result = DesktopTaskResult.model_validate_json(text)
                if live_events:
                    meta = dict(result.metadata or {})
                    meta["live_events"] = live_events
                    result = result.model_copy(update={"metadata": meta})
                return result
            except asyncio.TimeoutError:
                # Kill the stalled process; next call will restart it cleanly.
                self._process.kill()
                self._process = None
                return DesktopTaskResult(
                    status="failure",
                    successful_actions=0,
                    total_actions=0,
                    error=f"Desktop task timed out after {int(timeout)}s",
                    reason="desktop_task_timeout",
                    metadata={"app_context": payload.get("target_app", "generic"), "timeout_seconds": timeout},
                )

    async def close(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.stdin.write(b"__QUIT__\n")
                await self._process.stdin.drain()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except Exception:
                self._process.kill()
        self._process = None


async def get_or_create_desktop_session(session_id: str) -> DesktopSession:
    if session_id not in _ACTIVE_DESKTOP_SESSIONS:
        _ACTIVE_DESKTOP_SESSIONS[session_id] = DesktopSession(session_id)
    return _ACTIVE_DESKTOP_SESSIONS[session_id]


async def close_desktop_session(session_id: str) -> None:
    session = _ACTIVE_DESKTOP_SESSIONS.pop(session_id, None)
    if session:
        await session.close()


def _resolve_backend_script() -> str:
    spec = importlib.util.find_spec("generic_backend")
    if spec is None or spec.origin is None:
        raise RuntimeError("generic_backend is not available in this environment")
    return spec.origin


def _build_subprocess_env() -> dict[str, str]:
    """Preserve repo import boundaries for child processes launched from temp cwd values."""

    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    raw_pythonpath = env.get("PYTHONPATH", "")
    entries: list[str] = [
        str(repo_root),
        str(repo_root / "unified-app"),
        str(repo_root / "api-accessibility-poc"),
        str(repo_root / "cli-automation-poc"),
    ]

    for raw_entry in raw_pythonpath.split(os.pathsep):
        if not raw_entry:
            continue
        entry_path = Path(raw_entry)
        if not entry_path.is_absolute():
            entry_path = (repo_root / raw_entry).resolve()
        normalized = str(entry_path)
        if normalized not in entries:
            entries.append(normalized)

    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _parse_worker_output(
    *,
    stdout: str,
    stderr: str,
    target_app: str,
    child_exit_code: int,
) -> DesktopTaskResult:
    stdout = (stdout or "").strip()
    stderr = (stderr or "").strip()
    if not stdout:
        return DesktopTaskResult(
            status="failure",
            successful_actions=0,
            total_actions=0,
            error=stderr or "Desktop worker returned no output",
            reason="desktop_worker_start_failed",
            metadata={
                "app_context": target_app,
                "child_exit_code": child_exit_code,
            },
        )

    live_events: list[dict] = []
    result_line = ""
    for line in stdout.splitlines():
        if line.startswith("[EVT]"):
            try:
                live_events.append(json.loads(line[5:]))
            except Exception:
                pass
        elif line.strip():
            result_line = line.strip()

    if not result_line:
        return DesktopTaskResult(
            status="failure",
            successful_actions=0,
            total_actions=0,
            error=stderr or "Desktop worker returned no result line",
            reason="desktop_worker_start_failed",
            metadata={
                "app_context": target_app,
                "child_exit_code": child_exit_code,
            },
        )

    try:
        result = DesktopTaskResult.model_validate_json(result_line)
        if live_events:
            meta = dict(result.metadata or {})
            meta["live_events"] = live_events
            result = result.model_copy(update={"metadata": meta})
        return result
    except Exception as exc:
        return DesktopTaskResult(
            status="failure",
            successful_actions=0,
            total_actions=0,
            error=f"Invalid desktop worker output: {exc}",
            reason="desktop_worker_start_failed",
            metadata={
                "app_context": target_app,
                "child_exit_code": child_exit_code,
                "worker_stdout": result_line[:500],
            },
        )


def _write_clipboard(text: str) -> None:
    """Write text to the Windows clipboard before launching a desktop subprocess.

    Called by run_desktop_automation / run_desktop_automation_async when the
    orchestrator has handed off content (e.g. text scraped by the browser agent)
    that the desktop backend will paste via Ctrl+V.  Fails gracefully — a
    clipboard write failure is logged as a warning and execution continues.
    """
    try:
        import win32clipboard  # type: ignore[import-untyped]
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        logger.info("[DesktopAdapter] clipboard set: %d chars", len(text))
    except Exception as clip_exc:
        logger.warning("[DesktopAdapter] clipboard write failed: %s", clip_exc)


def _flight_report_metadata(session_id: str | None, objective_id: str | None) -> dict[str, str]:
    if not session_id or not objective_id:
        return {}
    return {
        "session_id": session_id,
        "objective_id": objective_id,
        "flight_report_path": str(_FLIGHT_REPORT_ROOT / session_id / objective_id / "report.json"),
    }


def _build_desktop_success_output(task: TaskInput, app_name: str) -> str | None:
    description = (task.description or "").strip().rstrip(".")
    lowered = description.lower()

    if task.context.get("paste_action"):
        return f"Pasted clipboard content into {app_name}"
    if task.context.get("focus_only"):
        return f"Focused {app_name}"
    if lowered.startswith(f"open {app_name.lower()} and create a new blank document"):
        return f"Open {app_name}"
    if lowered.startswith(("open ", "launch ", "start ", "run ")):
        return description
    return None


def run_desktop_automation(
    objective: str,
    target_app: str,
    expected_outcome: str | None = None,
    max_retries: int = 3,
    app_exe_path: str | None = None,
    runtime_timeout_seconds: float | None = None,
    clipboard_content: str | None = None,
    prior_results: dict | None = None,
    world_state: dict | None = None,
    session_id: str | None = None,
    objective_id: str | None = None,
) -> DesktopTaskResult:
    timeout_seconds = float(
        runtime_timeout_seconds or os.getenv("TRINITY_DESKTOP_TIMEOUT", DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS)
    )
    session_id = session_id or f"desktop-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    objective_id = objective_id or f"desktop-obj-{datetime.now().strftime('%H%M%S')}"
    # Layer 1: write OS clipboard before the subprocess launches so Ctrl+V finds content
    if clipboard_content:
        _write_clipboard(clipboard_content)
    payload = {
        "objective": objective,
        "target_app": target_app,
        "expected_outcome": expected_outcome,
        "max_retries": max_retries,
        "app_exe_path": app_exe_path,
        "runtime_timeout_seconds": runtime_timeout_seconds,
        "prior_results": prior_results,   # Layer 2: cross-objective context
        "world_state": world_state,        # Layer 3: structured world state
        "session_id": session_id,
        "objective_id": objective_id,
    }
    command = [
        sys.executable,
        _resolve_backend_script(),
        "--desktop-task",
        json.dumps(payload),
    ]

    try:
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_handle, tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8"
        ) as stderr_handle:
            completed = subprocess.run(
                command,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=_build_subprocess_env(),
            )
            stdout = completed.stdout
            stderr = completed.stderr
            if stdout is None:
                stdout_handle.seek(0)
                stdout = stdout_handle.read()
            if stderr is None:
                stderr_handle.seek(0)
                stderr = stderr_handle.read()
    except subprocess.TimeoutExpired:
        return DesktopTaskResult(
            status="failure",
            successful_actions=0,
            total_actions=0,
            error=f"Desktop task timed out after {int(timeout_seconds)}s",
            reason="desktop_task_timeout",
            metadata={
                "app_context": target_app,
                "timeout_seconds": timeout_seconds,
            },
        )

    typed_result = _parse_worker_output(
        stdout=stdout,
        stderr=stderr,
        target_app=target_app,
        child_exit_code=completed.returncode,
    )
    typed_result.metadata = {
        **dict(typed_result.metadata or {}),
        **_flight_report_metadata(session_id, objective_id),
    }
    return typed_result


async def run_desktop_automation_async(
    objective: str,
    target_app: str,
    expected_outcome: str | None = None,
    max_retries: int = 3,
    app_exe_path: str | None = None,
    runtime_timeout_seconds: float | None = None,
    clipboard_content: str | None = None,
    prior_results: dict | None = None,
    world_state: dict | None = None,
    cancel_event: Any = None,
    session_id: str | None = None,
    objective_id: str | None = None,
) -> DesktopTaskResult:
    """Run desktop automation through an async subprocess to avoid threadpool waits."""

    timeout_seconds = float(
        runtime_timeout_seconds or os.getenv("TRINITY_DESKTOP_TIMEOUT", DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS)
    )
    session_id = session_id or f"desktop-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    objective_id = objective_id or f"desktop-obj-{datetime.now().strftime('%H%M%S')}"
    # Layer 1: write OS clipboard before the subprocess launches
    if clipboard_content:
        _write_clipboard(clipboard_content)
    payload = {
        "objective": objective,
        "target_app": target_app,
        "expected_outcome": expected_outcome,
        "max_retries": max_retries,
        "app_exe_path": app_exe_path,
        "runtime_timeout_seconds": runtime_timeout_seconds,
        "prior_results": prior_results,   # Layer 2: cross-objective context
        "world_state": world_state,        # Layer 3: structured world state
        "session_id": session_id,
        "objective_id": objective_id,
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        _resolve_backend_script(),
        "--desktop-task",
        json.dumps(payload),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_build_subprocess_env(),
    )

    communicate_task = asyncio.ensure_future(process.communicate())
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    try:
        while not communicate_task.done():
            # Check cooperative cancellation
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                await communicate_task
                return DesktopTaskResult(
                    status="failure",
                    successful_actions=0,
                    total_actions=0,
                    error="Desktop task cancelled by user.",
                    reason="cancelled",
                    metadata={"app_context": target_app},
                )
            # Check wall-clock timeout
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                process.kill()
                await communicate_task
                return DesktopTaskResult(
                    status="failure",
                    successful_actions=0,
                    total_actions=0,
                    error=f"Desktop task timed out after {int(timeout_seconds)}s",
                    reason="desktop_task_timeout",
                    metadata={"app_context": target_app, "timeout_seconds": timeout_seconds},
                )
            await asyncio.sleep(min(0.2, remaining))

        stdout_bytes, stderr_bytes = communicate_task.result()
    except asyncio.CancelledError:
        process.kill()
        await asyncio.gather(communicate_task, return_exceptions=True)
        raise

    typed_result = _parse_worker_output(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        target_app=target_app,
        child_exit_code=process.returncode or 0,
    )
    typed_result.metadata = {
        **dict(typed_result.metadata or {}),
        **_flight_report_metadata(session_id, objective_id),
    }
    return typed_result


class DesktopAdapter(TaskAdapter):
    """Adapter for api-accessibility-poc module."""

    def __init__(self):
        self.module_name = "api-accessibility-poc"
        self._observed_windows: set[str] = set()
        self._observed_elements: set[str] = set()
        self._observed_text: str = ""

    def _effective_timeout(self, task: TaskInput) -> float:
        return float(task.timeout) if task.timeout is not None else DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS

    def _is_cancelled(self, task: TaskInput) -> bool:
        cancel_event = getattr(task, "cancel_event", None)
        return bool(cancel_event is not None and cancel_event.is_set())

    def _contract_metadata(self, task: TaskInput, *, effective_timeout: float, raw_result: dict | None = None) -> dict:
        metadata = {
            "module": self.module_name,
            "effective_timeout_seconds": effective_timeout,
            "effective_max_retries": task.max_retries,
        }
        if raw_result is not None:
            metadata["raw_result"] = raw_result
        return metadata

    def _contract_failure(self, task: TaskInput, *, effective_timeout: float, category: str, error: str) -> TaskResult:
        metadata = self._contract_metadata(task, effective_timeout=effective_timeout)
        metadata["adapter_name"] = self.module_name
        metadata["domain"] = task.domain
        return TaskResult(
            task_id=task.task_id,
            status="failure",
            category=category,
            code=failure_code(category),
            retriable=is_retriable(category),
            error=error,
            execution_log=[],
            artifacts=[],
            metadata=metadata,
        )

    def _normalize_category(self, typed_result: DesktopTaskResult) -> str:
        if typed_result.status == "success":
            return "success"
        if typed_result.reason == "desktop_task_timeout":
            return "timeout"

        combined = " ".join(
            part for part in (
                typed_result.reason or "",
                typed_result.error or "",
            )
            if part
        ).lower()
        if any(token in combined for token in AUTH_TOKENS):
            return "auth_failure"
        if any(token in combined for token in USER_ERROR_TOKENS):
            return "user_error"
        return "backend_error"

    async def execute(self, task: TaskInput) -> TaskResult:
        """Execute desktop task using the bounded subprocess wrapper."""
        import logging
        logger = logging.getLogger(__name__)
        
        effective_timeout = self._effective_timeout(task)
        if self._is_cancelled(task):
            emit_event(TASK_CANCELLED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name="desktop"))
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="cancelled",
                error="Task cancelled before execution started.",
            )

        _t0 = time.monotonic()
        emit_event(TASK_STARTED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name="desktop"))

        try:
            app_name = task.context.get("app_name", "generic")
            app_exe_path = task.context.get("app_exe_path")
            clipboard_content = task.context.get("clipboard_content")   # Layer 1
            prior_results = task.context.get("_prior_results")          # Layer 2
            world_state = task.context.get("_world_state")              # Layer 3
            desktop_session_id = task.context.get("_desktop_session_id")

            logger.info(
                "[DESKTOP_ADAPTER] Received task: description=%s app_name=%s "
                "clipboard=%s prior_results_keys=%s world_state_active_app=%s session=%s",
                task.description, app_name,
                f"{len(clipboard_content)} chars" if clipboard_content else "none",
                list(prior_results.keys()) if prior_results else "none",
                world_state.get("active_app") if world_state else "none",
                desktop_session_id or "one-shot",
            )

            if desktop_session_id:
                # Session mode: route through the persistent subprocess so app
                # windows and COM handles survive between consecutive calls.
                payload = {
                    "objective": task.description,
                    "target_app": app_name,
                    "expected_outcome": task.expected_outcome,
                    "max_retries": task.max_retries,
                    "app_exe_path": app_exe_path,
                    "runtime_timeout_seconds": effective_timeout,
                    "clipboard_content": clipboard_content,
                    "prior_results": prior_results,
                    "world_state": world_state,
                    "session_id": desktop_session_id,
                    "objective_id": task.task_id,
                }
                session = await get_or_create_desktop_session(desktop_session_id)
                typed_result = await session.run_task(payload, timeout=effective_timeout)
            else:
                typed_result = await run_desktop_automation_async(
                    objective=task.description,
                    target_app=app_name,
                    expected_outcome=task.expected_outcome,
                    max_retries=task.max_retries,
                    app_exe_path=app_exe_path,
                    runtime_timeout_seconds=effective_timeout,
                clipboard_content=clipboard_content,
                prior_results=prior_results,
                world_state=world_state,
                cancel_event=getattr(task, "cancel_event", None),
                )
            success_output = (
                _build_desktop_success_output(task, app_name)
                if typed_result.status == "success"
                else None
            )

            _duration = (time.monotonic() - _t0) * 1000
            _status = "success" if typed_result.status == "success" else "failure"
            emit_event(
                TASK_SUCCEEDED if _status == "success" else TASK_FAILED,
                make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name="desktop", duration_ms=_duration, extra={"status": _status}),
            )
            return TaskResult(
                task_id=task.task_id,
                status=_status,
                category=self._normalize_category(typed_result),
                error=typed_result.error or typed_result.reason,
                execution_log=[
                    ExecutionLog(
                        step=log.step,
                        action=log.action,
                        result=log.result,
                        details=log.details,
                        timestamp=datetime.now().isoformat(),
                    )
                    for log in typed_result.execution_log
                ],
                artifacts=[],
                metadata={
                    **self._contract_metadata(
                        task,
                        effective_timeout=effective_timeout,
                        raw_result=typed_result.model_dump(),
                    ),
                    **_flight_report_metadata(
                        typed_result.metadata.get("session_id"),
                        typed_result.metadata.get("objective_id"),
                    ),
                    "success_rate": typed_result.success_rate,
                    **({"output": success_output} if success_output else {}),
                },
            )
        except Exception as e:
            _duration = (time.monotonic() - _t0) * 1000
            emit_event(TASK_FAILED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name="desktop", duration_ms=_duration, extra={"error": str(e)}))
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="backend_error",
                error=f"Desktop adapter error: {str(e)}",
            )

    async def close_session(self, session_id: str) -> None:
        """Close a persistent desktop session and its subprocess."""
        await close_desktop_session(session_id)

    async def health_check(self) -> bool:
        """Check if desktop backend and runner are available."""
        try:
            _resolve_backend_script()
            return True
        except RuntimeError:
            return False

    async def wait_for_process(self, app_name: str, timeout: float) -> None:
        """Poll process availability by attempting a lightweight focus operation."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            probe = await self.execute(
                TaskInput(
                    task_id=f"wait-process-{int(time.time() * 1000)}",
                    description=f"Focus window with title containing '{app_name}'",
                    domain="desktop",
                    context={"focus_only": True, "app_name": app_name},
                )
            )
            if probe.status == "success":
                self._observed_windows.add(app_name)
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for process '{app_name}'")

    async def wait_for_window_title(self, title: str, timeout: float) -> None:
        """Poll for a visible window title using adapter execution probes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if title in self._observed_windows:
                return
            probe = await self.execute(
                TaskInput(
                    task_id=f"wait-window-{int(time.time() * 1000)}",
                    description=f"Focus window with title containing '{title}'",
                    domain="desktop",
                    context={"focus_only": True},
                )
            )
            if probe.status == "success":
                self._observed_windows.add(title)
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for window title '{title}'")

    async def wait_for_ui_element(self, element_name: str, element_type: str | None, timeout: float) -> None:
        """Poll for a UI element by probing with an element-focused click objective."""
        deadline = time.time() + timeout
        identity = f"{element_name}:{element_type or ''}"
        while time.time() < deadline:
            if identity in self._observed_elements:
                return
            descriptor = f"{element_name} ({element_type})" if element_type else element_name
            probe = await self.execute(
                TaskInput(
                    task_id=f"wait-element-{int(time.time() * 1000)}",
                    description=f"Click desktop element '{descriptor}'",
                    domain="desktop",
                    context={},
                )
            )
            if probe.status == "success":
                self._observed_elements.add(identity)
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for desktop element '{element_name}'")

    async def wait_for_text_in_window(self, text: str, timeout: float) -> None:
        """Poll for text in active window via repeated read-style probes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if text and text in self._observed_text:
                return
            probe = await self.execute(
                TaskInput(
                    task_id=f"wait-text-{int(time.time() * 1000)}",
                    description=f"Read text in active window and look for '{text}'",
                    domain="desktop",
                    context={},
                )
            )
            payload = str(probe.metadata.get("raw_result", {}))
            if text in payload:
                self._observed_text = payload
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for text '{text}' in active window")

    def get_capabilities(self) -> Dict:
        """Return desktop module capabilities conforming to schema v1."""
        return {
            "schema_version": "1.0",
            "domain": "desktop",
            "actions": ["click", "type", "open_app", "close_app", "read_element", "screenshot"],
            "limits": {
                "timeout_seconds": DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS,
                "max_retries": 3,
            },
            "constraints": {
                "thread_safe": False,
                "async": False,
                "platforms": ["Windows"],
            },
            "flight_reports": True,
        }
