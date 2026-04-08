"""Core orchestration workflow for planning and task execution."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal

from .clarification_engine import ClarificationEngine
from .database import HistoryManager
from .error_handler import ErrorHandler
from .event_bus import get_event_bus
from .execution_runner import TaskExecutionRunner
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
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"

    def cancel(self) -> None:
        """Request cancellation for next safe checkpoint."""
        self._cancelled = True
        self._cancel_event.set()

    def resume(self) -> None:
        """Unblock the agent loop after a human-in-the-loop pause."""
        self._resume_event.set()

    def run(self) -> None:
        """Thread entry point."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._execute())
        except Exception as exc:  # pragma: no cover - guarded by tests on error signal path
            self.error.emit(str(exc))
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
            watcher.frame_captured.connect(self.event_bus.frame_captured.emit)
            watcher.frame_rate_updated.connect(self.event_bus.frame_rate_updated.emit)
            self.screenshot_watcher = watcher
        return self.screenshot_watcher

    async def _execute(self) -> None:
        provider = make_provider(self.provider_name, self.api_key)
        from .prompt_registry import PromptRegistry

        registry = PromptRegistry(self.provider_name)
        runner = TaskExecutionRunner(
            run_id=self.run_id,
            task_description=self.task_description,
            domain=self.domain,
            event_bus=self.event_bus,
            history_manager=self.history_manager,
            error_handler=self.error_handler,
            planner=MacroPlanner(provider, registry=registry),
            provider=provider,
            bridge=TrinityBridge(),
            screenshot_watcher=self._ensure_screenshot_watcher(),
            cancel_requested=lambda: self._cancelled,
            cancel_event=self._cancel_event,
            resume_event=self._resume_event,
            approved_plan=self.approved_plan,
            provider_name=self.provider_name,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )
        await runner.execute()


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
        self.event_bus.task_cancel_requested.connect(
            self.cancel_current_task,
            Qt.ConnectionType.QueuedConnection,
        )

    def on_task_submitted(self, task_description: str, domain: str) -> None:
        """Start a new orchestration run if idle."""
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

    def resume_agent(self) -> None:
        """Resume a paused agent after the user resolves a blocker."""
        if self.current_worker is not None:
            self.current_worker.resume()
            get_event_bus().blocker_resolved.emit()

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
            domain = self._detect_domain(task_summary)
            plan = await planner.generate_plan(task_summary, domain)
            return [step.strip() for step in plan.steps if step.strip()] or [task_summary]
        finally:
            provider_close = getattr(provider, "close", None)
            if callable(provider_close):
                await provider_close()

    def _detect_domain(self, description: str) -> str:
        """Infer a coarse execution domain for pre-run objective generation."""
        lowered = description.lower()
        web_tokens = ("browser", "website", "google", "navigate", "search", "wikipedia", "web page", "url", "site")
        desktop_tokens = ("notepad", "calculator", "window", "desktop", "application", "tab")
        cli_tokens = ("directory", "terminal", "command", "shell", "powershell", "cmd", "files in current directory")
        hits = {
            "web": any(token in lowered for token in web_tokens),
            "desktop": any(token in lowered for token in desktop_tokens),
            "cli": any(token in lowered for token in cli_tokens),
        }
        matched = [domain for domain, active in hits.items() if active]
        if len(matched) > 1:
            return "mixed"
        return matched[0] if matched else "cli"
