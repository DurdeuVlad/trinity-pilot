"""Core orchestration workflow for planning and task execution."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from collections import deque
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal

from .clarification_engine import ClarificationEngine
from .crash_reporter import write_crash_dump as _write_crash_dump
from .database import HistoryManager, TaskStatus
from .error_handler import ErrorHandler
from .event_bus import get_event_bus
from .macro_planner import MacroPlanner
from .providers.factory import make_provider
from .screenshot_watcher import ScreenshotWatcher
from .settings_manager import SettingsManager
from .trinity_bridge import TrinityBridge

logger = logging.getLogger(__name__)

CONTRACT_TIMEOUT_SECONDS = 600
CONTRACT_MAX_RETRIES = 3
THREAD_CLEANUP_TIMEOUT_MS = 3000


def _shutdown_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Drain pending tasks before closing an ad-hoc worker loop."""
    try:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        shutdown_default_executor = getattr(loop, "shutdown_default_executor", None)
        if callable(shutdown_default_executor):
            loop.run_until_complete(shutdown_default_executor())
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _normalize_execution_domain(domain: str, description: str) -> str:
    normalized = (domain or "").strip().lower()
    if normalized in {"browser", "web"}:
        return "web"
    if normalized in {"desktop", "cli"}:
        return normalized
    if normalized == "mixed":
        lowered = description.lower()
        if any(token in lowered for token in ("browser", "website", "url", "http", "https", "google", "github")):
            return "web"
        if any(token in lowered for token in ("notepad", "window", "desktop", "application")):
            return "desktop"
        return "cli"
    return "cli"


def _select_target_server(domain: str, description: str) -> str | None:
    normalized = _normalize_execution_domain(domain, description)
    env_name = f"TRINITY_{normalized.upper()}_MCP_SERVER"
    configured = (os.getenv(env_name) or "").strip()
    if configured:
        return configured
    if normalized == "web" and any(token in description.lower() for token in ("puppeteer", "chrome devtools")):
        return "puppeteer_mcp"
    return None


class OrchestratorWorker(QObject):
    """Executes full workflow in a worker thread."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        task_description: str,
        domain: str,
        *,
        provider_name: str = "gemini",
        api_key: str = "",
        timeout_seconds: int = CONTRACT_TIMEOUT_SECONDS,
        max_retries: int = CONTRACT_MAX_RETRIES,
        frame_rate_limit: int = 5,
        max_frame_count: int = 100,
        approved_plan: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.task_description = task_description
        self.domain = domain
        self.provider_name = provider_name
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.frame_rate_limit = frame_rate_limit
        self.max_frame_count = max_frame_count
        self.approved_plan = list(approved_plan or [])
        self.event_bus = get_event_bus()
        self.history_manager = HistoryManager()
        self.error_handler = ErrorHandler()
        self.screenshot_watcher: ScreenshotWatcher | None = None
        self._cancelled = False
        self._cancel_event = threading.Event()
        self._resume_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially
        self._steer_lock = threading.Lock()
        self._steer_queue: deque[str] = deque()
        self._termination_status = "cancelled"
        self._termination_category = "cancelled"
        self._termination_reason = "Stopped — cancelled by you."
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"

    def cancel(
        self,
        *,
        reason: str = "Stopped — cancelled by you.",
        status: str = "cancelled",
        category: str = "cancelled",
    ) -> None:
        """Request cancellation for next safe checkpoint."""
        self._termination_reason = str(reason or "Stopped — cancelled by you.")
        self._termination_status = str(status or "cancelled")
        self._termination_category = str(category or "cancelled")
        self._cancelled = True
        self._cancel_event.set()
        self._pause_event.set()  # unblock any pause wait so loop can see cancel

    def termination_context(self) -> dict[str, str]:
        return {
            "reason": self._termination_reason,
            "status": self._termination_status,
            "category": self._termination_category,
        }

    def pause(self) -> None:
        """Pause the agent loop between action turns."""
        self._pause_event.clear()

    def resume(self) -> None:
        """Unblock the agent loop after a human-in-the-loop pause or CAPTCHA."""
        self._resume_event.set()
        self._pause_event.set()

    def submit_steer(self, text: str) -> None:
        """Queue mid-run user guidance for the next safe decision turn."""
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return
        with self._steer_lock:
            self._steer_queue.append(cleaned[:280])

    def consume_steer(self) -> str:
        """Drain queued steer text in arrival order for the current objective."""
        with self._steer_lock:
            if not self._steer_queue:
                return ""
            combined = "\n".join(self._steer_queue)
            self._steer_queue.clear()
        return combined[:1000]

    def clear_steer(self) -> None:
        """Discard any pending steer text at objective boundaries."""
        with self._steer_lock:
            self._steer_queue.clear()

    def run(self) -> None:
        """Thread entry point."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._execute())
        except BaseException as exc:  # pragma: no cover - guarded by tests on error signal path
            _write_crash_dump(
                exc,
                run_id=getattr(self, "run_id", "unknown"),
                task_description=getattr(self, "task_description", ""),
                phase="worker_thread",
            )
            if isinstance(exc, Exception):
                self.error.emit(str(exc))
            else:
                raise
        finally:
            _shutdown_event_loop(loop)
            self.finished.emit()

    def _ensure_screenshot_watcher(self) -> ScreenshotWatcher:
        """Create the screenshot watcher lazily in the worker thread."""
        if self.screenshot_watcher is None:
            watcher = ScreenshotWatcher(
                max_fps=self.frame_rate_limit,
                max_frames=self.max_frame_count,
                parent=self,
            )
            self.screenshot_watcher = watcher
        return self.screenshot_watcher

    async def _execute(self) -> None:
        finalized_objectives = [step.strip() for step in self.approved_plan if step.strip()] or [self.task_description]
        normalized_domain = _normalize_execution_domain(self.domain, self.task_description)
        target_server = _select_target_server(self.domain, self.task_description)
        bridge = TrinityBridge()

        self.history_manager.create_task(
            self.run_id,
            self.task_description,
            normalized_domain,
            plan_steps=finalized_objectives,
            estimated_duration=max(60, len(finalized_objectives) * 60),
            confidence=0.95 if self.approved_plan else 0.8,
        )
        for index, step in enumerate(finalized_objectives, start=1):
            self.history_manager.add_step(self.run_id, index, step)
        self.history_manager.start_task(self.run_id)

        self.event_bus.run_started.emit(self.run_id)
        self.event_bus.execution_started.emit()
        self.event_bus.plan_generated.emit(finalized_objectives)
        self.event_bus.emit_status(
            f"Desktop finalized the objective and selected MCP server '{target_server}' for domain '{normalized_domain}'.",
            "info",
        )

        if self._cancelled:
            payload = {"status": "cancelled", "category": "cancelled", "error": self._termination_reason}
            self.history_manager.complete_task(
                self.run_id,
                result_data=payload,
                error_message=self._termination_reason,
                status=TaskStatus.CANCELLED,
            )
            self.event_bus.execution_complete.emit(payload)
            self.event_bus.execution_ended.emit()
            self.event_bus.run_ended.emit(self.run_id)
            return

        result_payload: dict[str, object]
        try:
            await bridge.initialize()
            self.event_bus.step_started.emit(1, finalized_objectives[0])
            self.history_manager.update_step_status(self.run_id, 1, TaskStatus.RUNNING)
            result = await bridge.execute_task(
                task_id=self.run_id,
                description=self.task_description,
                domain=normalized_domain,
                target_server=target_server,
                objective_steps=finalized_objectives,
                context={
                    "selected_domain": normalized_domain,
                    "selected_mcp_server": target_server,
                    "approved_objectives": finalized_objectives,
                },
                timeout=self.timeout_seconds,
                max_retries=self.max_retries,
                cancel_event=self._cancel_event,
            )
            result_payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        except Exception as exc:
            payload = self.error_handler.handle(exc, context="Execution", category="backend_error")
            user_message = str(payload.get("user_message") or "Execution failed.")
            failure_payload = {
                "status": "failure",
                "category": str(payload.get("category") or "backend_error"),
                "error": user_message,
                "message": str(payload.get("message") or exc),
                "error_details": payload.get("error_details", {}),  # ← PRESERVE ERROR DETAILS
                "run_id": self.run_id,
                "objective": self.objectives[0] if self.objectives else None,
            }
            self.history_manager.update_step_status(
                self.run_id,
                1,
                TaskStatus.FAILED,
                result_data=failure_payload,
                error_message=user_message,
            )
            self.history_manager.complete_task(
                self.run_id,
                result_data=failure_payload,
                error_message=user_message,
                status=TaskStatus.FAILED,
            )
            self.event_bus.step_failed.emit(1, user_message)
            self.event_bus.emit_status(user_message, "error")
            self.event_bus.execution_complete.emit(failure_payload)
            self.event_bus.execution_ended.emit()
            self.event_bus.run_ended.emit(self.run_id)
            return
        finally:
            await bridge.shutdown()

        metadata = result_payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        output_text = str(
            metadata.get("output")
            or result_payload.get("error")
            or result_payload.get("status")
            or ""
        )
        step_result = {
            "status": str(result_payload.get("status") or "unknown"),
            "category": str(result_payload.get("category") or ""),
            "output": output_text,
        }
        succeeded = step_result["status"] == "success"
        terminal_status = TaskStatus.COMPLETED if succeeded else TaskStatus.FAILED

        for index, step in enumerate(finalized_objectives, start=1):
            if index > 1:
                self.event_bus.step_started.emit(index, step)
            if succeeded:
                self.history_manager.update_step_status(
                    self.run_id,
                    index,
                    TaskStatus.COMPLETED,
                    result_data=step_result,
                )
                self.event_bus.step_completed.emit(index, step_result)
            else:
                self.history_manager.update_step_status(
                    self.run_id,
                    index,
                    TaskStatus.FAILED,
                    result_data=step_result,
                    error_message=output_text or "Execution failed.",
                )
                self.event_bus.step_failed.emit(index, output_text or "Execution failed.")

        # Build complete result data with all metadata
        complete_result_data = {
            "status": step_result["status"],
            "category": step_result["category"],
            "output": output_text,
            "target_server": target_server,
        }
        
        # Include full metadata from TaskResult (contains health_check_error, etc.)
        if metadata:
            complete_result_data["metadata"] = metadata
        
        # Include error details if present in result_payload
        if "error" in result_payload:
            complete_result_data["error"] = result_payload["error"]
        
        self.history_manager.complete_task(
            self.run_id,
            result_data=complete_result_data,
            error_message=None if succeeded else (output_text or "Execution failed."),
            status=terminal_status,
        )

        summary = {
            "status": step_result["status"],
            "category": step_result["category"],
            "target_server": target_server,
            "domain": normalized_domain,
            "objective_count": len(finalized_objectives),
        }
        self.event_bus.task_result_ready.emit(output_text or "Execution finished.", summary)
        self.event_bus.execution_complete.emit({
            "status": step_result["status"],
            "category": step_result["category"],
            "output": output_text,
            "target_server": target_server,
            "domain": normalized_domain,
        })
        self.event_bus.execution_ended.emit()
        self.event_bus.run_ended.emit(self.run_id)


class OrchestratorCore(QObject):
    """Coordinates UI events and background orchestration workers."""

    def __init__(self) -> None:
        super().__init__()
        self.event_bus = get_event_bus()
        self.settings_manager = SettingsManager()
        self.runtime_settings = self.settings_manager.load()
        self.current_thread: Optional[QThread] = None
        self.current_worker: Optional[OrchestratorWorker] = None
        self._pending_worker_error: Optional[dict[str, str]] = None
        self._startup_guard_message: Optional[str] = None
        self._clarification_engine: Optional[ClarificationEngine] = None
        self._clarification_thread: Optional[threading.Thread] = None
        self._task_running = False
        self._approved_plan_override: list[str] | None = None

        self.event_bus.task_submitted.connect(
            self.on_task_submitted,
            Qt.ConnectionType.QueuedConnection,
        )
        self.event_bus.pipe_task_submitted.connect(
            self.on_pipe_task_submitted,
            Qt.ConnectionType.QueuedConnection,
        )
        self.event_bus.task_cancel_requested.connect(
            self.cancel_current_task,
            Qt.ConnectionType.QueuedConnection,
        )
        self.event_bus.task_policy_stop_requested.connect(
            self.request_policy_stop,
            Qt.ConnectionType.QueuedConnection,
        )
        self.event_bus.steer_input.connect(
            self.on_steer_input,
            Qt.ConnectionType.QueuedConnection,
        )

    def on_task_submitted(self, task_description: str, domain: str) -> None:
        """Start a new orchestration run if idle."""
        self._accept_submission(task_description, domain)

    def on_pipe_task_submitted(self, task_description: str, domain: str, request_id: str) -> None:
        """Start a new orchestration run for a request-aware pipe submission."""
        self._accept_submission(task_description, domain, request_id=request_id)

    def _accept_submission(self, task_description: str, domain: str, request_id: str | None = None) -> None:
        """Start a new orchestration run if idle and publish any request/run mapping."""
        block_reason = self.get_submission_block_reason()
        if block_reason is not None:
            self.event_bus.emit_status(block_reason, "warning")
            return

        self._pending_worker_error = None
        self.event_bus.emit_status("Task accepted. Starting orchestrator...", "info")
        self.event_bus.emit_status(f"Effective domain: {domain}.", "info")
        self.event_bus.set_busy(True)
        if domain in {"browser", "desktop", "mixed"}:
            self.event_bus.desktop_takeover_started.emit(domain)
        self._start_worker(task_description, domain)
        if request_id and self.current_worker is not None:
            self.event_bus.pipe_task_registered.emit(request_id, self.current_worker.run_id)

    def handle_chat_message(self, user_text: str) -> None:
        """Process a chat message through the clarification engine in a background thread."""
        if self._startup_guard_message is not None:
            self.event_bus.chat_message.emit("assistant", self._startup_guard_message)
            return

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            display_text = user_text
            try:
                engine = self._get_clarification_engine()
                result = loop.run_until_complete(engine.process(user_text))
                if result.ready:
                    display_text = result.confirmed_task or user_text
                    preview_steps = loop.run_until_complete(
                        self._generate_objective_preview(display_text)
                    )
                    self.event_bus.chat_message.emit(
                        "assistant",
                        (
                            f'Got it. I turned "{display_text}" into a proposed execution plan. '
                            "Review the objectives below, edit anything that looks off, then approve to run."
                        ),
                    )
                    self.event_bus.objectives_preview_ready.emit(display_text, preview_steps)
                else:
                    self.event_bus.chat_message.emit("assistant", result.text)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Objective preview failed; falling back to direct run readiness: %s", exc)
                self.event_bus.chat_message.emit(
                    "assistant",
                    (
                        f'Got it - I am ready to run "{display_text}". '
                        "I could not build the editable objective list this time, but you can still run it or keep refining."
                    ),
                )
                self.event_bus.clarification_ready.emit(display_text)
            finally:
                _shutdown_event_loop(loop)

        self._clarification_thread = threading.Thread(target=_run, daemon=True)
        self._clarification_thread.start()

    def _get_clarification_engine(self) -> ClarificationEngine:
        """Return the ClarificationEngine for the current session."""
        if self._clarification_engine is None:
            provider_name = str(self.runtime_settings.get("ai_provider", "gemini")).lower()
            api_key = self._resolve_api_key(provider_name)
            provider = make_provider(provider_name, api_key)
            self._clarification_engine = ClarificationEngine(provider)
        return self._clarification_engine

    def reset_chat_session(self) -> None:
        """Clear clarification history so a new conversation starts fresh."""
        if self._clarification_engine is not None:
            self._clarification_engine.reset()
        self._approved_plan_override = None

    def set_startup_guard(self, message: Optional[str]) -> None:
        """Block task submission until startup readiness is satisfied."""
        self._startup_guard_message = message

    def get_submission_block_reason(self) -> str | None:
        """Return user-facing block reason when a task cannot be accepted."""
        if self._task_running:
            return "Task is already running."
        if self._startup_guard_message is not None:
            return self._startup_guard_message
        return None

    def get_reset_block_reason(self) -> str | None:
        """Return user-facing block reason when run-state reset is unsafe."""
        if self._task_running:
            return "Task is already running."
        return None

    def update_runtime_settings(self, settings: dict[str, object]) -> None:
        """Refresh the execution defaults used for future worker runs."""
        merged = dict(self.runtime_settings)
        merged.update(settings)
        self.runtime_settings = merged

    def set_plan_override(self, approved_plan: list[str] | None) -> None:
        """Store a user-approved objective list for the next submitted task."""
        self._approved_plan_override = [step.strip() for step in (approved_plan or []) if step.strip()] or None

    def regenerate_objective_preview(self, task_summary: str) -> None:
        """Rebuild the editable objective preview without submitting the task."""
        if self._startup_guard_message is not None:
            self.event_bus.chat_message.emit("assistant", self._startup_guard_message)
            return

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                preview_steps = loop.run_until_complete(
                    self._generate_objective_preview(task_summary)
                )
                self.event_bus.chat_message.emit(
                    "assistant",
                    "I refreshed the objectives. Review the updated plan and approve it when it looks right.",
                )
                self.event_bus.objectives_preview_ready.emit(task_summary, preview_steps)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Objective regeneration failed: %s", exc)
                self.event_bus.chat_message.emit(
                    "assistant",
                    (
                        "I could not regenerate the objectives automatically right now. "
                        "You can keep editing the current list or run it as-is."
                    ),
                )
                self.event_bus.objectives_modify_done.emit(False)
            finally:
                _shutdown_event_loop(loop)

        self._clarification_thread = threading.Thread(target=_run, daemon=True)
        self._clarification_thread.start()

    def modify_objectives_preview(
        self, task_summary: str, current_objectives: list[str], change_request: str
    ) -> None:
        """Apply a user-requested natural-language change to the objectives list via the LLM."""
        if self._startup_guard_message is not None:
            self.event_bus.chat_message.emit("assistant", self._startup_guard_message)
            return

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                from .objectives_decomposer import ObjectivesModifier
                from .prompt_registry import PromptRegistry

                provider_name = str(self.runtime_settings.get("ai_provider", "gemini")).lower()
                api_key = self._resolve_api_key(provider_name)
                provider = make_provider(provider_name, api_key)
                try:
                    modifier = ObjectivesModifier(provider, registry=PromptRegistry(provider_name))
                    updated, rejection = loop.run_until_complete(
                        modifier.modify(current_objectives, change_request, task_summary)
                    )
                finally:
                    provider_close = getattr(provider, "close", None)
                    if callable(provider_close):
                        loop.run_until_complete(provider_close())

                if rejection is None:
                    self.event_bus.chat_message.emit(
                        "assistant",
                        "Done. I updated the objectives — review the revised plan and approve when it looks right.",
                    )
                    self.event_bus.objectives_preview_ready.emit(task_summary, updated)
                    self.event_bus.objectives_modify_done.emit(True)
                else:
                    self.event_bus.chat_message.emit("assistant", rejection)
                    self.event_bus.objectives_modify_done.emit(False)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Objectives modification failed: %s", exc)
                self.event_bus.chat_message.emit(
                    "assistant",
                    "I could not process that change right now. You can keep editing or run the current plan.",
                )
                self.event_bus.objectives_modify_done.emit(False)
            finally:
                _shutdown_event_loop(loop)

        self._clarification_thread = threading.Thread(target=_run, daemon=True)
        self._clarification_thread.start()

    def _resolve_api_key(self, provider_name: str) -> str:
        """Read the active API key from env or saved settings."""
        if provider_name == "openai":
            return os.getenv("OPENAI_API_KEY") or str(self.runtime_settings.get("openai_api_key", ""))
        if os.getenv("GEMINI_MOCK", ""):
            return "mock"
        return os.getenv("GEMINI_API_KEY") or str(self.runtime_settings.get("gemini_api_key", ""))

    def _start_worker(self, task_description: str, domain: str) -> None:
        provider_name = str(self.runtime_settings.get("ai_provider", "gemini")).lower()
        api_key = self._resolve_api_key(provider_name)
        approved_plan = list(self._approved_plan_override or [])
        self._approved_plan_override = None

        self.current_thread = QThread()
        self.current_worker = OrchestratorWorker(
            task_description,
            domain,
            provider_name=provider_name,
            api_key=api_key,
            timeout_seconds=int(self.runtime_settings.get("default_timeout_seconds", 60)),
            max_retries=int(self.runtime_settings.get("max_retries", 3)),
            frame_rate_limit=int(self.runtime_settings.get("frame_rate_limit", 5)),
            max_frame_count=int(self.runtime_settings.get("max_frame_count", 100)),
            approved_plan=approved_plan,
        )
        self._task_running = True
        self.current_worker.moveToThread(self.current_thread)

        self.current_thread.started.connect(self.current_worker.run)
        self.current_thread.finished.connect(self._on_thread_finished)
        self.current_worker.finished.connect(self._on_worker_finished)
        self.current_worker.finished.connect(self.current_thread.quit)
        self.current_worker.error.connect(self._on_worker_error)

        self.current_thread.start()

    def cancel_current_task(self) -> None:
        """Forward cancel request to active worker."""
        if self.current_worker is not None:
            self.current_worker.cancel()

    def request_policy_stop(self, reason: str) -> None:
        """Fail closed with an explicit policy-terminated state."""
        if self.current_worker is None:
            return
        clean_reason = str(reason or "Policy stop requested").strip() or "Policy stop requested"
        self.current_worker.cancel(
            reason=clean_reason,
            status="policy_terminated",
            category="policy_stop",
        )

    def resume_agent(self) -> None:
        """Resume a paused agent after the user resolves a blocker."""
        if self.current_worker is not None:
            self.current_worker.resume()
            get_event_bus().blocker_resolved.emit()

    def pause_agent(self) -> None:
        """Pause the running agent between action turns."""
        if self.current_worker is not None:
            self.current_worker.pause()

    def on_steer_input(self, text: str) -> None:
        """Queue advisory steer text for the active worker."""
        if self.current_worker is None:
            return
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return
        self.current_worker.submit_steer(cleaned)
        self.event_bus.emit_status("Steer queued for the next decision turn.", "info")

    def _on_worker_finished(self) -> None:
        if self._pending_worker_error is not None:
            self.event_bus.execution_complete.emit(
                {"status": "failure", "error": self._pending_worker_error["message"]}
            )
            self._pending_worker_error = None

        if getattr(self.current_worker, "domain", None) in {"browser", "desktop", "mixed"}:
            self.event_bus.desktop_takeover_ended.emit()

        self._cleanup_worker_state()
        self.event_bus.set_busy(False)

    def _on_worker_error(self, error: str) -> None:
        payload = ErrorHandler().handle(RuntimeError(error), context="Orchestration", category="backend_error")
        self.event_bus.emit_status(payload["user_message"], "error")
        self._pending_worker_error = payload

    def _on_thread_finished(self) -> None:
        """Handle late thread teardown when the thread stops after worker cleanup."""
        if self.current_thread is not None or self.current_worker is not None:
            self._cleanup_worker_state()

    def _cleanup_worker_state(self) -> None:
        thread = self.current_thread
        worker = self.current_worker

        if thread is not None:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(THREAD_CLEANUP_TIMEOUT_MS):
                    terminate = getattr(thread, "terminate", None)
                    if callable(terminate):
                        terminate()
                        thread.wait(1000)
            thread.deleteLater()
            self.current_thread = None

        if worker is not None:
            worker.deleteLater()
            self.current_worker = None

        self._task_running = False

    def shutdown(self, timeout_ms: int = THREAD_CLEANUP_TIMEOUT_MS) -> bool:
        """Attempt deterministic shutdown; return False if worker thread refuses to stop."""
        self.cancel_current_task()
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.quit()
            if not self.current_thread.wait(timeout_ms):
                self.event_bus.emit_status("Could not stop active task yet. Try closing again.", "warning")
                return False
        self._cleanup_worker_state()
        
        # Close provider to cleanup Gemini async client
        if hasattr(self, '_provider') and self._provider is not None:
            provider_close = getattr(self._provider, "close", None)
            if callable(provider_close):
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Schedule cleanup but don't wait (app is shutting down)
                        asyncio.ensure_future(provider_close())
                    else:
                        # Run cleanup synchronously if loop is stopped
                        loop.run_until_complete(asyncio.wait_for(provider_close(), timeout=2.0))
                except Exception as e:
                    import logging
                    logging.warning(f"Provider cleanup failed: {e}")
        
        return True

    async def _generate_objective_preview(self, task_summary: str) -> list[str]:
        """Build a pre-execution objective list for user review."""
        from .macro_planner import MacroPlanner
        from .prompt_registry import PromptRegistry

        provider_name = str(self.runtime_settings.get("ai_provider", "gemini")).lower()
        api_key = self._resolve_api_key(provider_name)
        provider = make_provider(provider_name, api_key)
        try:
            planner = MacroPlanner(provider, registry=PromptRegistry(provider_name))
            bridge = TrinityBridge()
            # Note: bridge initialization is needed for deep suggestion, 
            # but we use coarse fallback if not initialized.
            domain = bridge.suggest_domain(task_summary)
            plan = await planner.generate_plan(task_summary, domain)
            return [step.strip() for step in plan.steps if step.strip()] or [task_summary]
        finally:
            provider_close = getattr(provider, "close", None)
            if callable(provider_close):
                await provider_close()

    def _detect_domain(self, description: str) -> str:
        """Infer a coarse execution domain for pre-run objective generation."""
        return TrinityBridge().suggest_domain(description)
