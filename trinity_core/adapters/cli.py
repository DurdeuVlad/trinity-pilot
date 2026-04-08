"""CLI automation adapter."""
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from cli_backend import run_cli_automation
from cli_io_models import CLITaskResult
from cli_validator import CommandValidator
from ..adapter import TaskAdapter
from ..models import TaskInput, TaskResult, ExecutionLog, failure_code, is_retriable


DEFAULT_CONTRACT_TIMEOUT_SECONDS = 600
_FLIGHT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "unified-app" / "_runtime" / "flight_reports"
AUTH_CATEGORY_TOKENS = {"auth", "auth_failure"}
TIMEOUT_CATEGORY_TOKENS = {"timeout"}
USER_ERROR_CATEGORY_TOKENS = {"user_error", "need_assistance"}
AUTH_MESSAGE_TOKENS = ("api_key_invalid", "invalid api key", "api key not valid", "unauthenticated", "authentication failed")

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
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="cancelled",
                error="Task cancelled before execution started.",
            )

        try:
            prior_results = task.context.get("_prior_results")  # Layer 2

            # Run sync backend in a separate thread
            typed_result: CLITaskResult = await asyncio.to_thread(
                run_cli_automation,
                objective=task.description,
                expected_outcome=task.expected_outcome or "Task completed",
                max_retries=task.max_retries,
                timeout=effective_timeout,
                prior_results=prior_results,
            )
            self._last_output_text = "\n".join(
                (log.output or "") for log in typed_result.execution_log if log.output
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
                        details=log.output or log.error,
                        timestamp=datetime.now().isoformat()
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
                    **self._flight_report_metadata(
                        session_id=typed_result.metadata.get("session_id"),
                        objective_id=typed_result.metadata.get("objective_id"),
                    ),
                    "success_rate": typed_result.success_rate,
                }
            )
        except Exception as e:
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
            "glass_box": True,
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
