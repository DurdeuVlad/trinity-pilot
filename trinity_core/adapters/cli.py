"""CLI automation adapter."""
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from cli_backend import CLIBackend, run_cli_automation
from cli_io_models import CLITaskResult
from cli_validator import CommandValidator
from ..adapter import TaskAdapter
from ..models import TaskInput, TaskResult, ExecutionLog, failure_code, is_retriable
from ..verification import build_failure_verification, build_verification
from ..telemetry import (
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_SUCCEEDED,
    emit_event,
    make_event_payload,
)


DEFAULT_CONTRACT_TIMEOUT_SECONDS = 600
_FLIGHT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "unified-app" / "_runtime" / "flight_reports"
AUTH_CATEGORY_TOKENS = {"auth", "auth_failure"}
TIMEOUT_CATEGORY_TOKENS = {"timeout"}
USER_ERROR_CATEGORY_TOKENS = {"user_error", "need_assistance"}
AUTH_MESSAGE_TOKENS = ("api_key_invalid", "invalid api key", "api key not valid", "unauthenticated", "authentication failed")

# ---------------------------------------------------------------------------
# CLI session pool — one CLIBackend instance per task run
# ---------------------------------------------------------------------------

_ACTIVE_CLI_SESSIONS: Dict[str, CLIBackend] = {}


def get_or_create_cli_session(session_id: str) -> CLIBackend:
    if session_id not in _ACTIVE_CLI_SESSIONS:
        _ACTIVE_CLI_SESSIONS[session_id] = CLIBackend()
    return _ACTIVE_CLI_SESSIONS[session_id]


def close_cli_session(session_id: str) -> None:
    backend = _ACTIVE_CLI_SESSIONS.pop(session_id, None)
    if backend:
        backend.close()

class CLIAdapter(TaskAdapter):
    """Adapter for cli-automation-poc module."""
    
    def __init__(self):
        self.module_name = "cli-automation-poc"
        self._last_output_text: str = ""
        self._active_processes: dict[str, bool] = {}

    def _effective_timeout(self, task: TaskInput) -> int:
        return int(task.timeout) if task.timeout is not None else DEFAULT_CONTRACT_TIMEOUT_SECONDS

    def _is_cancelled(self, task: TaskInput) -> bool:
        cancel_event = getattr(task, "cancel_event", None)
        return bool(cancel_event is not None and cancel_event.is_set())

    def _contract_metadata(self, task: TaskInput, *, effective_timeout: int, raw_result: dict | None = None) -> dict:
        metadata = {
            "module": self.module_name,
            "effective_timeout_seconds": effective_timeout,
            "effective_max_retries": task.max_retries,
        }
        if raw_result is not None:
            metadata["raw_result"] = raw_result
        return metadata

    def _flight_report_metadata(self, *, session_id: str | None, objective_id: str | None) -> dict[str, str]:
        if not session_id or not objective_id:
            return {}
        return {
            "flight_report_session_id": session_id,
            "flight_report_objective_id": objective_id,
            "flight_report_path": str(_FLIGHT_REPORT_ROOT / session_id / objective_id / "report.json"),
        }

    def _contract_failure(self, task: TaskInput, *, effective_timeout: int, category: str, error: str) -> TaskResult:
        metadata = self._contract_metadata(task, effective_timeout=effective_timeout)
        metadata["adapter_name"] = self.module_name
        metadata["domain"] = task.domain
        verification = build_failure_verification(
            module="cli",
            error=error,
            evidence={"category": category},
        )
        metadata["verification"] = verification.model_dump()
        return TaskResult(
            task_id=task.task_id,
            status="failure",
            category=category,
            code=failure_code(category),
            retriable=is_retriable(category),
            error=error,
            execution_log=[],
            artifacts=[],
            verification=verification,
            metadata=metadata,
        )

    def _normalize_category(self, typed_result: CLITaskResult) -> str:
        if typed_result.status == "success":
            return "success"

        raw_category = ""
        if isinstance(typed_result.metadata, dict):
            raw_category = str(typed_result.metadata.get("failure_category", "")).lower()

        reason = (typed_result.reason or "").lower()
        error = (typed_result.error or "").lower()
        combined = " ".join(part for part in (raw_category, reason, error) if part)

        if raw_category in AUTH_CATEGORY_TOKENS or any(token in combined for token in AUTH_MESSAGE_TOKENS):
            return "auth_failure"
        if raw_category in TIMEOUT_CATEGORY_TOKENS or "timed out" in combined or "timeout" in combined:
            return "timeout"
        if raw_category in USER_ERROR_CATEGORY_TOKENS:
            return "user_error"
        return "backend_error"
    
    async def execute(self, task: TaskInput) -> TaskResult:
        """Execute CLI task using backend wrapper."""
        effective_timeout = self._effective_timeout(task)
        if self._is_cancelled(task):
            emit_event(TASK_CANCELLED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name))
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="cancelled",
                error="Task cancelled before execution started.",
            )

        _t0 = time.monotonic()
        emit_event(TASK_STARTED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name))

        try:
            prior_results = task.context.get("_prior_results")  # Layer 2
            cli_session_id = task.context.get("_cli_session_id")
            progress_cb = task.context.get("_cli_progress_cb")

            # Reuse a session-level CLIBackend when a session ID is in context
            # so the SmartOrchestrator retains shell state across calls.
            reuse_backend = get_or_create_cli_session(cli_session_id) if cli_session_id else None

            # Run sync backend in a separate thread
            typed_result: CLITaskResult = await asyncio.to_thread(
                run_cli_automation,
                objective=task.description,
                expected_outcome=task.expected_outcome or "Task completed",
                max_retries=task.max_retries,
                timeout=effective_timeout,
                prior_results=prior_results,
                session_id=task.task_id,
                objective_id=task.task_id,
                _reuse_backend=reuse_backend,
                progress_cb=progress_cb,
            )
            self._last_output_text = "\n".join(
                (log.output or "") for log in typed_result.execution_log if log.output
            )

            _duration = (time.monotonic() - _t0) * 1000
            _status = "success" if typed_result.status == "success" else "failure"
            execution_log = [
                ExecutionLog(
                    step=log.step,
                    action=log.action,
                    result=log.result,
                    details=log.output or log.error,
                    timestamp=datetime.now().isoformat()
                )
                for log in typed_result.execution_log
            ]
            verification = build_verification(
                task=task,
                module="cli",
                backend_result=typed_result.model_dump(),
                task_status=_status,
                execution_log=execution_log,
                output_text=self._last_output_text,
            )
            emit_event(
                TASK_SUCCEEDED if _status == "success" else TASK_FAILED,
                make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name, duration_ms=_duration, extra={"status": _status}),
            )
            return TaskResult(
                task_id=task.task_id,
                status=_status,
                category=self._normalize_category(typed_result),
                error=typed_result.error or typed_result.reason,
                execution_log=execution_log,
                artifacts=[],
                verification=verification,
                metadata={
                    **self._contract_metadata(
                        task,
                        effective_timeout=effective_timeout,
                        raw_result=typed_result.model_dump(),
                    ),
                    **self._flight_report_metadata(
                        session_id=typed_result.metadata.get("session_id"),
                        objective_id=typed_result.metadata.get("objective_id"),
                    ),
                    "success_rate": typed_result.success_rate,
                    "verification": verification.model_dump(),
                }
            )
        except Exception as e:
            _duration = (time.monotonic() - _t0) * 1000
            emit_event(TASK_FAILED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name, duration_ms=_duration, extra={"error": str(e)}))
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="backend_error",
                error=f"CLI adapter error: {str(e)}",
            )
    
    async def health_check(self) -> bool:
        """Check if CLI module is available."""
        try:
            from smart_orchestrator import SmartOrchestrator
            return True
        except ImportError:
            return False

    async def close_session(self, session_id: str) -> None:
        """Close a persistent CLI session and release its backend resources."""
        close_cli_session(session_id)
    
    def get_capabilities(self) -> Dict:
        """Return CLI module capabilities conforming to schema v1."""
        capability_families = getattr(CommandValidator, "CAPABILITY_FAMILIES", {})
        return {
            "schema_version": "1.0",
            "domain": "cli",
            "actions": sorted(capability_families.keys()) or ["run_command"],
            "limits": {
                "timeout_seconds": DEFAULT_CONTRACT_TIMEOUT_SECONDS,
                "max_retries": 5,
            },
            "constraints": {
                "thread_safe": False,
                "async": False,
                "platforms": ["Windows"],
            },
            "flight_reports": True,
            "policy_bounded": True,
        }

    async def wait_for_output_contains(self, text: str, timeout: float) -> None:
        """Poll recent command output until expected text appears."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if text in self._last_output_text:
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for CLI output containing '{text}'")

    async def wait_for_process_exit(self, process_id: str, timeout: float) -> None:
        """Poll tracked process state until process is no longer active."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._active_processes.get(process_id, False):
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for process '{process_id}' to exit")

    async def wait_for_file_condition(self, file_path: str, condition: str, timeout: float) -> None:
        """Poll file system conditions: exists, modified, or size."""
        deadline = time.time() + timeout
        normalized = condition.lower()
        initial_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else None
        while time.time() < deadline:
            exists = os.path.exists(file_path)
            if normalized == "exists" and exists:
                return
            if normalized == "modified" and exists and initial_mtime is not None and os.path.getmtime(file_path) > initial_mtime:
                return
            if normalized == "size" and exists and os.path.getsize(file_path) > 0:
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(
            f"Timed out waiting for file condition '{condition}' on '{file_path}'"
        )
