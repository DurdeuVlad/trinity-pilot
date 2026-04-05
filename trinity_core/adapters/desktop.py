"""Desktop automation adapter."""

import asyncio
import importlib.util
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from desktop_io_models import DesktopTaskResult

logger = logging.getLogger(__name__)

from ..adapter import TaskAdapter
from ..models import ExecutionLog, TaskInput, TaskResult, failure_code, is_retriable


DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS = 600.0
AUTH_TOKENS = ("api_key_invalid", "invalid api key", "api key not valid", "unauthenticated", "authentication failed")
USER_ERROR_TOKENS = ("clarify", "need assistance", "invalid objective", "unsafe request")


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

    try:
        return DesktopTaskResult.model_validate_json(stdout)
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
                "worker_stdout": stdout[:500],
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
    glass_box_mode: bool = True,
    app_exe_path: str | None = None,
    runtime_timeout_seconds: float | None = None,
    clipboard_content: str | None = None,
    prior_results: dict | None = None,
    world_state: dict | None = None,
) -> DesktopTaskResult:
    timeout_seconds = float(
        runtime_timeout_seconds or os.getenv("TRINITY_DESKTOP_TIMEOUT", DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS)
    )
    # Layer 1: write OS clipboard before the subprocess launches so Ctrl+V finds content
    if clipboard_content:
        _write_clipboard(clipboard_content)
    payload = {
        "objective": objective,
        "target_app": target_app,
        "expected_outcome": expected_outcome,
        "max_retries": max_retries,
        "glass_box_mode": glass_box_mode,
        "app_exe_path": app_exe_path,
        "prior_results": prior_results,   # Layer 2: cross-objective context
        "world_state": world_state,        # Layer 3: structured world state
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

    return _parse_worker_output(
        stdout=stdout,
        stderr=stderr,
        target_app=target_app,
        child_exit_code=completed.returncode,
    )


async def run_desktop_automation_async(
    objective: str,
    target_app: str,
    expected_outcome: str | None = None,
    max_retries: int = 3,
    glass_box_mode: bool = True,
    app_exe_path: str | None = None,
    runtime_timeout_seconds: float | None = None,
    clipboard_content: str | None = None,
    prior_results: dict | None = None,
    world_state: dict | None = None,
    cancel_event: Any = None,
) -> DesktopTaskResult:
    """Run desktop automation through an async subprocess to avoid threadpool waits."""

    timeout_seconds = float(
        runtime_timeout_seconds or os.getenv("TRINITY_DESKTOP_TIMEOUT", DEFAULT_DESKTOP_RUNTIME_TIMEOUT_SECONDS)
    )
    # Layer 1: write OS clipboard before the subprocess launches
    if clipboard_content:
        _write_clipboard(clipboard_content)
    payload = {
        "objective": objective,
        "target_app": target_app,
        "expected_outcome": expected_outcome,
        "max_retries": max_retries,
        "glass_box_mode": glass_box_mode,
        "app_exe_path": app_exe_path,
        "prior_results": prior_results,   # Layer 2: cross-objective context
        "world_state": world_state,        # Layer 3: structured world state
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

    return _parse_worker_output(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        target_app=target_app,
        child_exit_code=process.returncode or 0,
    )


class DesktopAdapter(TaskAdapter):
    """Adapter for api-accessibility-poc module."""

    def __init__(self):
        self.module_name = "api-accessibility-poc"

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
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="cancelled",
                error="Task cancelled before execution started.",
            )

        try:
            app_name = task.context.get("app_name", "generic")
            glass_box = task.context.get("glass_box", False)
            app_exe_path = task.context.get("app_exe_path")
            clipboard_content = task.context.get("clipboard_content")   # Layer 1
            prior_results = task.context.get("_prior_results")          # Layer 2
            world_state = task.context.get("_world_state")              # Layer 3

            logger.info(
                "[DESKTOP_ADAPTER] Received task: description=%s app_name=%s "
                "clipboard=%s prior_results_keys=%s world_state_active_app=%s",
                task.description, app_name,
                f"{len(clipboard_content)} chars" if clipboard_content else "none",
                list(prior_results.keys()) if prior_results else "none",
                world_state.get("active_app") if world_state else "none",
            )

            typed_result: DesktopTaskResult = await run_desktop_automation_async(
                objective=task.description,
                target_app=app_name,
                expected_outcome=task.expected_outcome,
                max_retries=task.max_retries,
                glass_box_mode=glass_box,
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

            return TaskResult(
                task_id=task.task_id,
                status="success" if typed_result.status == "success" else "failure",
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
                    "success_rate": typed_result.success_rate,
                    **({"output": success_output} if success_output else {}),
                },
            )
        except Exception as e:
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="backend_error",
                error=f"Desktop adapter error: {str(e)}",
            )

    async def health_check(self) -> bool:
        """Check if desktop backend and runner are available."""
        try:
            _resolve_backend_script()
            return True
        except RuntimeError:
            return False

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
            "glass_box": True,
            "flight_reports": True,
        }
