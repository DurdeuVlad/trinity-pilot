"""Core orchestration workflow for planning and task execution."""
from __future__ import annotations

import asyncio
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

CONTRACT_TIMEOUT_SECONDS = 600
CONTRACT_MAX_RETRIES = 3
THREAD_CLEANUP_TIMEOUT_MS = 3000


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
        self.event_bus = get_event_bus()
        self.history_manager = HistoryManager()
        self.error_handler = ErrorHandler()
        self.screenshot_watcher: ScreenshotWatcher | None = None
        self._cancelled = False
        self._cancel_event = threading.Event()
        self.run_id = f"run_{uuid.uuid4().hex[:12]}"

    def cancel(self) -> None:
        """Request cancellation for next safe checkpoint."""
        self._cancelled = True
        self._cancel_event.set()

    def run(self) -> None:
        """Thread entry point."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._execute())
        except Exception as exc:  # pragma: no cover - guarded by tests on error signal path
            self.error.emit(str(exc))
        finally:
            loop.close()
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
            try:
                engine = self._get_clarification_engine()
                result = loop.run_until_complete(engine.process(user_text))
                if result.ready:
                    display_text = result.confirmed_task or user_text
                    self.event_bus.chat_message.emit(
                        "assistant",
                        f"Got it - I'm ready to run:\n\"{display_text}\"\n\nClick Run Workflow to start, or keep chatting to refine.",
                    )
                    self.event_bus.clarification_ready.emit(display_text)
                else:
                    self.event_bus.chat_message.emit("assistant", result.text)
            except Exception as exc:  # pragma: no cover - defensive
                self.event_bus.chat_message.emit("assistant", f"Sorry, I hit an error: {exc}")
            finally:
                loop.close()

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
