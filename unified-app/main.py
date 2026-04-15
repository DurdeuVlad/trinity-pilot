"""Orchestrator Desktop App — main window."""
from __future__ import annotations

import asyncio
import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure repo-local modules are importable when running the app directly from
# the unified-app/ directory.
_REPO_ROOT = Path(__file__).parent.parent.resolve()
for _relative_path in (
    ".",
    "api-accessibility-poc",
    "browser-gui-automation",
    "cli-automation-poc",
    "audit-debugger/src",
):
    _import_path = str((_REPO_ROOT / _relative_path).resolve())
    if _import_path not in sys.path:
        sys.path.insert(0, _import_path)

from dotenv import load_dotenv


def _load_env() -> None:
    """Load module-local .env without overriding existing shell variables."""
    env_path = Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_env()

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from orchestrator import get_event_bus
from orchestrator.orchestrator_core import OrchestratorCore
from orchestrator.providers.factory import make_provider
from orchestrator.settings_manager import SettingsManager
from mcp_server.app_command_pipe import AppCommandPipeServer
from mcp_server.run_monitor import RunEventRecorder
from mcp_server.task_submission_pipe import TaskSubmissionPipeServer
from ui.overlay import ExecutionOverlay
from ui.panels import ExecutionPlanPanel, StatusLogPanel
from ui.panels.chat_panel import ChatPanel
from ui.theme import MUTED, PRIMARY, app_stylesheet
from ui.views.history_view import HistoryView
from ui.views.settings_view import SettingsView

# ---------------------------------------------------------------------------
# Domain detection helper (replaces the old combo-box heuristic)
# ---------------------------------------------------------------------------

def _detect_domain(description: str) -> str:
    """Select execution domain from task text heuristics."""
    lowered = description.lower()
    web_tokens = (
        "browser",
        "browser tab",
        "website",
        "web page",
        "webpage",
        "web",
        "google",
        "github",
        "navigate",
        "search",
        "wikipedia",
        "url",
        "site",
        "link",
        "chrome",
        "firefox",
        "edge",
        "http://",
        "https://",
    )
    desktop_tokens = ("notepad", "calculator", "window", "desktop", "application", "tab")
    cli_tokens = ("directory", "terminal", "command", "shell", "powershell", "cmd", "files in current directory")
    hits = {
        "web": any(t in lowered for t in web_tokens),
        "desktop": any(t in lowered for t in desktop_tokens),
        "cli": any(t in lowered for t in cli_tokens),
    }
    matched = [d for d, active in hits.items() if active]
    if len(matched) > 1:
        return "mixed"
    return matched[0] if matched else "cli"


# ---------------------------------------------------------------------------
# Global hotkey — Ctrl+Alt+End (Windows only, graceful no-op elsewhere)
# ---------------------------------------------------------------------------
_MOD_CONTROL = 0x0002
_MOD_ALT = 0x0001
_VK_END = 0x23
_HOTKEY_ID = 9901
_WM_HOTKEY = 0x0312


class _HotkeyFilter(QAbstractNativeEventFilter):
    """Intercepts WM_HOTKEY and calls a callback when our hotkey fires."""

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback
        self._registered = False
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, _HOTKEY_ID, _MOD_CONTROL | _MOD_ALT, _VK_END
            )
            self._registered = bool(ok)
        except Exception:
            pass

    def nativeEventFilter(self, event_type: bytes, message) -> tuple[bool, int]:
        if event_type == b"windows_generic_MSG":
            try:
                import ctypes.wintypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self._callback()
            except Exception:
                pass
        return False, 0

    def close(self) -> None:
        if self._registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
            except Exception:
                pass
            self._registered = False


def _install_stop_hotkey(callback) -> _HotkeyFilter:
    filt = _HotkeyFilter(callback)
    QApplication.instance().installNativeEventFilter(filt)  # type: ignore[union-attr]
    return filt

STARTUP_PREFLIGHT_TIMEOUT_SECONDS = 8.0
STARTUP_PREFLIGHT_RETRIES = 2
STARTUP_PREFLIGHT_RETRY_DELAY_SECONDS = 3.0


@dataclass(slots=True)
class StartupConfig:
    """Resolved runtime configuration for startup."""

    provider_name: str
    api_key: str | None
    key_source: str
    env_path: str | None


@dataclass(slots=True)
class StartupReadiness:
    """Startup verdict exposed to the UI before the first task runs."""

    provider_name: str
    ready: bool
    user_message: str
    block_task_submission: bool


def _module_env_path() -> Path:
    return Path(__file__).with_name(".env")


def _load_cli_planner_class():
    from cli_planner import CLIPlanner  # type: ignore[import-not-found]
    return CLIPlanner


def resolve_startup_config(env_path: Path | None = None) -> StartupConfig:
    """Resolve active provider and its API key without overriding shell env."""
    dotenv_path = env_path or _module_env_path()
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=False)

    settings = SettingsManager().load()
    provider_name = str(settings.get("ai_provider", "gemini")).lower()

    if provider_name == "gemini" and os.getenv("GEMINI_MOCK", ""):
        return StartupConfig(
            provider_name=provider_name,
            api_key="mock",
            key_source="environment",
            env_path=str(dotenv_path),
        )

    if provider_name == "openai":
        had_shell_key = bool(os.getenv("OPENAI_API_KEY"))
        api_key = os.getenv("OPENAI_API_KEY") or settings.get("openai_api_key", "").strip() or None
        key_source = "environment" if had_shell_key else ("settings" if api_key else "missing")
    else:
        had_shell_key = bool(os.getenv("GEMINI_API_KEY"))
        api_key = os.getenv("GEMINI_API_KEY") or settings.get("gemini_api_key", "").strip() or None
        key_source = "environment" if had_shell_key else ("settings" if api_key else "missing")

    return StartupConfig(
        provider_name=provider_name,
        api_key=api_key,
        key_source=key_source,
        env_path=str(dotenv_path),
    )


def _is_mock_startup(config: StartupConfig) -> bool:
    """Return whether startup should use the offline Gemini mock path."""
    return config.provider_name == "gemini" and (
        (config.api_key or "").strip().lower() == "mock"
        or bool(os.getenv("GEMINI_MOCK", ""))
    )


def _mock_startup_readiness(provider_name: str = "gemini") -> StartupReadiness:
    """Return the canonical mock-mode readiness state."""
    return StartupReadiness(
        provider_name=provider_name,
        ready=True,
        user_message="Startup mode: mock fallback ready.",
        block_task_submission=False,
    )


def _format_preflight_block_message(exc: Exception, provider_name: str) -> str:
    """Convert a startup preflight exception into a user-actionable message."""
    message = str(exc)
    lowered = message.lower()
    label = provider_name.capitalize()
    if "api key" in lowered or "api_key_invalid" in lowered or "unauth" in lowered or "incorrect api key" in lowered:
        return f"{label} blocked: invalid API key. Check your key in Settings."
    if "429" in lowered or "quota" in lowered or "resourceexhausted" in lowered or "rate limit" in lowered:
        return f"{label} blocked: quota or rate limit reached. Try again shortly."
    if "timeout" in lowered:
        return f"{label} blocked: startup preflight timed out. Check your network."
    safe_message = message.strip().splitlines()[0] if message.strip() else "startup preflight failed"
    return f"{label} blocked: {safe_message}."


def _is_retryable_preflight_message(message: str) -> bool:
    """Return whether a failed preflight looks transient enough to retry."""
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in (
            "timed out",
            "startup preflight failed",
            "service unreachable",
            "not reachable",
            "connection refused",
            "temporarily unavailable",
        )
    )


async def run_preflight(config: StartupConfig) -> StartupReadiness:
    """Probe the configured AI provider and CLI planner before allowing task submission."""
    if _is_mock_startup(config):
        return _mock_startup_readiness(config.provider_name)

    provider = None
    cli_planner = None
    try:
        provider = make_provider(config.provider_name, config.api_key or "")
        await asyncio.wait_for(provider.probe(), timeout=STARTUP_PREFLIGHT_TIMEOUT_SECONDS)

        cli_planner_class = _load_cli_planner_class()
        cli_planner = cli_planner_class(config.api_key)
        await asyncio.wait_for(
            asyncio.to_thread(cli_planner.probe_live_model),
            timeout=STARTUP_PREFLIGHT_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return StartupReadiness(
            provider_name=config.provider_name,
            ready=False,
            user_message=_format_preflight_block_message(exc, config.provider_name),
            block_task_submission=True,
        )
    finally:
        provider_close = getattr(provider, "close", None)
        if callable(provider_close):
            await provider_close()
        planner_client = getattr(cli_planner, "client", None)
        planner_close = getattr(planner_client, "close", None)
        if callable(planner_close):
            await asyncio.to_thread(planner_close)

    source = f" ({config.key_source})" if config.key_source != "missing" else ""
    return StartupReadiness(
        provider_name=config.provider_name,
        ready=True,
        user_message=f"{config.provider_name.capitalize()} ready.",
        block_task_submission=False,
    )


async def run_preflight_with_retries(
    config: StartupConfig,
    *,
    retries: int = STARTUP_PREFLIGHT_RETRIES,
    retry_delay_seconds: float = STARTUP_PREFLIGHT_RETRY_DELAY_SECONDS,
) -> StartupReadiness:
    """Retry transient startup preflight failures before blocking the app."""
    attempts = max(1, retries + 1)
    last_readiness: StartupReadiness | None = None

    for attempt in range(attempts):
        readiness = await run_preflight(config)
        last_readiness = readiness
        if readiness.ready:
            return readiness
        if attempt >= attempts - 1:
            return readiness
        if not _is_retryable_preflight_message(readiness.user_message):
            return readiness
        await asyncio.sleep(retry_delay_seconds)

    return last_readiness or StartupReadiness(
        provider_name=config.provider_name,
        ready=False,
        user_message=f"{config.provider_name.capitalize()} blocked: startup preflight failed.",
        block_task_submission=True,
    )


def evaluate_startup_readiness(config: StartupConfig) -> StartupReadiness:
    """Return the startup verdict before the UI becomes interactive.

    Only performs the fast synchronous key-presence check.  The live network
    probe is deferred to `MainWindow.start_async_preflight()` so the window
    can appear immediately without blocking.
    """
    if _is_mock_startup(config):
        return _mock_startup_readiness(config.provider_name)

    if not config.api_key:
        provider_label = config.provider_name.capitalize()
        env_var = "OPENAI_API_KEY" if config.provider_name == "openai" else "GEMINI_API_KEY"
        return StartupReadiness(
            provider_name=config.provider_name,
            ready=False,
            user_message=(
                f"{provider_label} blocked: API key missing. "
                f"Set {env_var} or enter the key in Settings."
            ),
            block_task_submission=True,
        )

    # Key is present — defer live probe; show "checking" state immediately.
    return StartupReadiness(
        provider_name=config.provider_name,
        ready=False,
        user_message=f"Checking {config.provider_name.capitalize()} connection…",
        block_task_submission=True,
    )


def _supports_window_raise() -> bool:
    """Return whether the current Qt platform supports raise/restore actions."""
    app = QApplication.instance()
    if app is None:
        return False
    return app.platformName().lower() not in {"offscreen", "minimal", "minimalegl"}


class MainWindow(QMainWindow):
    """Main application container."""

    def __init__(self, startup_readiness: StartupReadiness | None = None) -> None:
        super().__init__()
        self.event_bus = get_event_bus()
        self.orchestrator = OrchestratorCore()
        self.startup_readiness = startup_readiness
        self._force_mock_startup = _is_mock_startup(resolve_startup_config())
        self._run_layout_initialized = False
        self._was_maximized = False  # remember window state before AI takeover
        self._plan_total = 0
        self._setup_ui()
        self._overlay = ExecutionOverlay()   # must exist before signals are wired
        self._connect_signals()
        self._overlay.stop_requested.connect(self.event_bus.task_cancel_requested.emit)
        self._hotkey_filter = _install_stop_hotkey(
            lambda: self.event_bus.task_cancel_requested.emit()
        )
        self._run_monitor = RunEventRecorder(
            history_manager=self.history_view.history_manager,
            runtime_dir=Path(__file__).parent / "_runtime",
        )
        self._run_monitor.attach(self.event_bus)
        self._task_pipe_server = TaskSubmissionPipeServer(
            event_bus=self.event_bus,
            history_manager=self.history_view.history_manager,
            can_submit=self.orchestrator.get_submission_block_reason,
        )
        self._task_pipe_server.start()
        self._command_pipe_server = AppCommandPipeServer(
            event_bus=self.event_bus,
            history_manager=self.history_view.history_manager,
            run_monitor=self._run_monitor,
            can_submit=self.orchestrator.get_submission_block_reason,
            can_reset=self.orchestrator.get_reset_block_reason,
            resume_run=self.orchestrator.resume_agent,
            cancel_run=self.orchestrator.request_policy_stop,
            reset_session=self.event_bus.command_reset_requested.emit,
            shutdown_app=self.event_bus.command_shutdown_requested.emit,
        )
        self._command_pipe_server.start()
        if self.startup_readiness is not None:
            self.apply_startup_readiness(self.startup_readiness)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Orchestrator Desktop App")
        self.setMinimumSize(800, 560)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        run_tab = QWidget()
        run_layout = QVBoxLayout(run_tab)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(0)

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QSplitter

        # Vertical splitter: chat on top, execution panels on bottom.
        self.run_splitter = QSplitter(Qt.Orientation.Vertical)
        self.run_splitter.setHandleWidth(4)
        self.run_splitter.setChildrenCollapsible(False)

        # Chat panel (always visible)
        self.chat_panel = ChatPanel()
        self.run_splitter.addWidget(self.chat_panel)

        # Bottom container: execution plan (left) + status log (right)
        self.bottom_widget = QWidget()
        self.bottom_widget.setMinimumHeight(180)
        bottom_layout = QVBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(4)
        self.main_splitter.setChildrenCollapsible(False)

        self.execution_plan_panel = ExecutionPlanPanel()
        self.main_splitter.addWidget(self.execution_plan_panel)

        self.status_log_panel = StatusLogPanel()
        self.main_splitter.addWidget(self.status_log_panel)

        # Live view is shown via the on-screen HUD overlay; never in a panel — the frontend is minimized during execution.
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 3)
        bottom_layout.addWidget(self.main_splitter)
        self.run_splitter.addWidget(self.bottom_widget)

        # Initial proportions favor interaction over passive monitoring.
        self.run_splitter.setStretchFactor(0, 4)
        self.run_splitter.setStretchFactor(1, 2)
        self.run_splitter.setSizes([420, 210])
        self.main_splitter.setSizes([380, 320])

        run_layout.addWidget(self.run_splitter, stretch=1)

        self.history_view = HistoryView()
        self.settings_view = SettingsView()

        self.tabs.addTab(run_tab, "Run")
        self.tabs.addTab(self.history_view, "History")
        self.tabs.addTab(self.settings_view, "Settings")
        stylesheet = app_stylesheet()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        self.setStyleSheet(stylesheet)
        self._apply_runtime_settings(self.settings_view.settings_manager.load())
        QTimer.singleShot(0, self._apply_initial_run_layout)

    def _connect_signals(self) -> None:
        # ── Chat panel signals ─────────────────────────────────────────────
        self.chat_panel.message_sent.connect(self._on_chat_message_sent)
        self.chat_panel.run_requested.connect(self._on_run_requested)
        self.chat_panel.cancel_requested.connect(self.event_bus.task_cancel_requested.emit)
        self.chat_panel.objective_regenerate_requested.connect(self._on_objective_regenerate_requested)
        self.chat_panel.objective_change_requested.connect(self._on_objective_change_requested)
        self.chat_panel.new_task_requested.connect(self._on_new_task_requested)

        # ── Clarification replies back to chat ────────────────────────────
        self.event_bus.chat_message.connect(
            lambda role, text: self.chat_panel.add_message(role, text)
        )
        self.event_bus.chat_message.connect(
            lambda role, _text: self.chat_panel.set_input_enabled(True) if role == "assistant" else None
        )
        self.event_bus.clarification_ready.connect(self.chat_panel.set_run_ready)
        self.event_bus.objectives_preview_ready.connect(self.chat_panel.show_objective_editor)
        self.event_bus.objectives_modify_done.connect(
            lambda ok: None if ok else self.chat_panel.unblock_objective_editor()
        )

        # ── Task result back to chat ───────────────────────────────────────
        self.event_bus.task_result_ready.connect(
            lambda text, summary: self.chat_panel.add_result_card(text, summary)
        )

        # ── Execution panels (plan + log) ──────────────────────────────────
        self.history_view.task_selected.connect(self._show_history_task_details)
        self.history_view.load_into_chat_requested.connect(self._on_history_load_into_chat_requested)
        self.history_view.rerun_requested.connect(self._on_history_rerun_requested)

        self.event_bus.plan_generated.connect(self.execution_plan_panel.display_plan)
        self.event_bus.step_started.connect(lambda idx, _desc: self.execution_plan_panel.update_step_status(idx, "running"))
        self.event_bus.step_completed.connect(self.execution_plan_panel.on_step_completed)
        self.event_bus.step_failed.connect(self.execution_plan_panel.on_step_failed)
        self.event_bus.step_detail.connect(self.execution_plan_panel.add_step_detail)
        self.event_bus.plan_state_updated.connect(self.execution_plan_panel.on_plan_state_updated)
        self.event_bus.status_update.connect(self.status_log_panel.append_log)
        self.event_bus.app_busy.connect(self.chat_panel.set_executing)
        self.event_bus.app_busy.connect(self._on_app_busy)
        self.event_bus.execution_complete.connect(self._on_execution_complete)
        self.event_bus.execution_complete.connect(lambda _: self.setWindowTitle("TrinityPilot"))
        self.event_bus.execution_ended.connect(lambda: self.setWindowTitle("TrinityPilot"))
        self.event_bus.command_reset_requested.connect(self._on_new_task_requested)
        self.event_bus.command_shutdown_requested.connect(self.close)
        self.settings_view.settings_saved.connect(self._apply_runtime_settings)
        self.event_bus.desktop_takeover_started.connect(self._on_takeover_started)
        self.event_bus.desktop_takeover_ended.connect(self._on_takeover_ended)
        # ── HUD overlay — full step lifecycle ─────────────────────────────
        self.event_bus.plan_generated.connect(self._overlay.set_plan)
        self.event_bus.plan_generated.connect(self._on_plan_title)
        self.event_bus.step_started.connect(self._overlay.set_step_started)
        self.event_bus.step_started.connect(self._on_step_title)
        self.event_bus.step_completed.connect(
            lambda idx, _payload: self._overlay.set_step_completed(idx)
        )
        self.event_bus.step_failed.connect(
            lambda idx, _msg: self._overlay.set_step_failed(idx)
        )
        self.event_bus.status_update.connect(self._overlay.set_narration)
        self.event_bus.preflight_done.connect(self.apply_startup_readiness)
        self.event_bus.cli_step_progress.connect(self._on_cli_step)
        self.event_bus.blocker_detected.connect(self._overlay.show_blocker)
        self.event_bus.blocker_detected.connect(self._on_blocker_detected)
        self._overlay.continue_requested.connect(self.orchestrator.resume_agent)
        self._overlay.pause_requested.connect(self._on_pause_requested)
        self._overlay.steer_requested.connect(self.event_bus.steer_input.emit)

    def _on_chat_message_sent(self, text: str) -> None:
        """Route a user chat message to the clarification engine."""
        self.orchestrator.set_plan_override(None)
        self.orchestrator.handle_chat_message(text)

    def _on_run_requested(self, confirmed_task: str, approved_objectives: list[str]) -> None:
        """User approved a task and optionally curated its objective list."""
        self.orchestrator.set_plan_override(approved_objectives)
        domain = _detect_domain(confirmed_task)
        self._submit_task(confirmed_task, domain)

    def _on_objective_regenerate_requested(self, confirmed_task: str) -> None:
        """Refresh the proposed objective list without executing the task."""
        self.orchestrator.regenerate_objective_preview(confirmed_task)

    def _on_objective_change_requested(self, confirmed_task: str, current_objectives: list, change_request: str) -> None:
        """Apply a natural-language change request to the current objectives via the LLM."""
        self.orchestrator.modify_objectives_preview(confirmed_task, current_objectives, change_request)

    def _submit_task(self, task_description: str, domain: str) -> None:
        """Submit a task through the shared run entrypoint."""
        self._overlay.set_task(task_description)
        self.event_bus.task_submitted.emit(task_description, domain)

    def _show_history_task_details(self, task_id: str) -> None:
        """Present details for a selected history task."""
        if not self.history_view.show_task_details(task_id):
            self.event_bus.emit_status(f"Could not load details for task {task_id}", "warning")

    def _on_history_load_into_chat_requested(self, task_id: str) -> None:
        """Populate the chat composer from a historical task."""
        seed = self.history_view.build_chat_seed(task_id)
        if seed is None:
            self.event_bus.emit_status(f"Could not load task {task_id} into chat", "warning")
            return
        self.tabs.setCurrentIndex(0)
        self.orchestrator.set_plan_override(None)
        self.chat_panel.set_input_enabled(True)
        self.chat_panel.load_task_draft(
            seed,
            status_message=f"Loaded {task_id}. Edit the draft or press Enter to continue.",
        )
        self.event_bus.emit_status(f"Loaded task {task_id} into chat", "history")

    def _on_history_rerun_requested(self, task_id: str) -> None:
        """Reuse a historical task as a fresh submission."""
        details = self.history_view.get_task_details(task_id)
        if details is None:
            self.event_bus.emit_status(f"Could not rerun task {task_id}", "warning")
            return
        self.tabs.setCurrentIndex(0)
        self.orchestrator.set_plan_override(None)
        self.chat_panel.reset_for_new_session()
        self.chat_panel.add_message("assistant", f"Rerunning saved task {task_id}.")
        self.chat_panel.load_task_draft(
            details["description"],
            status_message=f"Rerunning {task_id} in the {details['domain']} domain.",
        )
        self._submit_task(details["description"], details["domain"])

    def apply_startup_readiness(self, readiness: StartupReadiness) -> None:
        """Reflect startup readiness in UI state and task-submission gating."""
        if self._force_mock_startup:
            readiness = _mock_startup_readiness(readiness.provider_name)
        self.chat_panel.set_startup_state(
            readiness.user_message,
            block_submission=readiness.block_task_submission,
        )
        self.orchestrator.set_startup_guard(
            readiness.user_message if readiness.block_task_submission else None
        )
        self.event_bus.emit_status(
            readiness.user_message,
            "warning" if readiness.block_task_submission else "startup",
        )

    def start_async_preflight(self, config: StartupConfig) -> None:
        """Run the live provider probe in a daemon thread; post result back via signal."""
        if self._force_mock_startup or _is_mock_startup(config):
            self.apply_startup_readiness(_mock_startup_readiness(config.provider_name))
            return
        import threading

        def _run() -> None:
            readiness = asyncio.run(run_preflight_with_retries(config))
            self.event_bus.preflight_done.emit(readiness)

        threading.Thread(target=_run, daemon=True).start()

    def _on_blocker_detected(self, _message: str) -> None:
        """Restore the app window when a CAPTCHA or human action is needed."""
        if _supports_window_raise():
            if self._was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()

    def _on_pause_requested(self) -> None:
        """Pause the running agent and surface the main window."""
        self.orchestrator.pause_agent()
        self._overlay.show_paused()
        if _supports_window_raise():
            if self._was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()

    def _on_new_task_requested(self) -> None:
        """Clear chat history and orchestrator session for a fresh start."""
        self.orchestrator.reset_chat_session()
        self.chat_panel.reset_for_new_session()
        self.event_bus.emit_status("Ready for new task.", "info")

    def _on_takeover_started(self, domain: str) -> None:
        """Minimise app and show full-screen HUD when a desktop backend starts."""
        self._was_maximized = self.isMaximized()
        self._overlay.show_for_domain(domain)
        if _supports_window_raise():
            self.showMinimized()

    def _on_cli_step(self, obj_index: int, step: dict) -> None:
        """Route CLI step progress events to the overlay and activity log."""
        event = step.get("event", "")
        if event == "plan_ready":
            self._overlay.set_plan(step.get("steps", []))
        elif event == "step_started":
            idx = step.get("step_index", 0) + 1
            self._overlay.set_step_started(idx, step.get("action", ""))
        elif event == "step_done":
            idx = step.get("step_index", 0) + 1
            if step.get("status") == "success":
                self._overlay.set_step_completed(idx)
                next_action = step.get("next_action")
                if next_action:
                    self._overlay.set_narration(f"-> Next: {next_action}", "info")
            else:
                self._overlay.set_step_failed(idx)
            self.status_log_panel.append_cli_step(obj_index, step)

    def _on_takeover_ended(self) -> None:
        """Restore app to its previous state and dismiss the HUD."""
        self._overlay.hide_overlay()
        if not _supports_window_raise():
            return
        if self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _apply_runtime_settings(self, settings: dict[str, object]) -> None:
        """Apply saved settings to the live UI and future orchestrator runs."""
        self.orchestrator.update_runtime_settings(settings)
        # If startup guard is active and a key was just entered, re-run preflight
        # so the user doesn't have to restart the app after entering their API key.
        if self.orchestrator._startup_guard_message is not None:
            new_config = resolve_startup_config()
            if self._force_mock_startup or _is_mock_startup(new_config):
                self.apply_startup_readiness(_mock_startup_readiness(new_config.provider_name))
            elif new_config.api_key:
                self.start_async_preflight(new_config)

    def _apply_initial_run_layout(self) -> None:
        """Give the Run workspace a chat-first layout on first paint."""
        if self._run_layout_initialized:
            return
        total_height = max(self.run_splitter.height(), self.height())
        top_height = max(420, int(total_height * 0.67))
        bottom_height = max(210, total_height - top_height)
        self.run_splitter.setSizes([top_height, bottom_height])
        self.main_splitter.setSizes([620, 360])
        self._set_execution_panels_collapsed(True)
        self._run_layout_initialized = True

    def _on_app_busy(self, busy: bool) -> None:
        """Expand monitoring during execution; leave panels visible when done."""
        if busy:
            self._set_execution_panels_collapsed(False)
            self.tabs.setTabText(0, "● Run")
            self.tabs.tabBar().setTabTextColor(0, QColor(PRIMARY))
        else:
            self.tabs.setTabText(0, "Run")
            self.tabs.tabBar().setTabTextColor(0, QColor(MUTED))

    def _on_execution_complete(self, _payload: dict) -> None:
        """Refresh history; leave panels visible so the user can review output."""
        self.history_view.load_history()

    def _on_plan_title(self, objectives: list) -> None:
        self._plan_total = len(objectives)
        self.setWindowTitle("TrinityPilot — Running\u2026")

    def _on_step_title(self, idx: int, desc: str) -> None:
        short = desc[:45] + ("\u2026" if len(desc) > 45 else "")
        self.setWindowTitle(f"TrinityPilot \u2014 {idx}/{self._plan_total}: {short}")

    def _set_execution_panels_collapsed(self, collapsed: bool) -> None:
        """Bias the vertical splitter toward chat while keeping monitoring visible."""
        total_height = max(self.run_splitter.height(), self.height(), 640)
        if collapsed:
            top_height = total_height
            bottom_height = 0
            self.bottom_widget.setMinimumHeight(180)
            self.bottom_widget.setMaximumHeight(240)
            self.bottom_widget.hide()
        else:
            self.bottom_widget.show()
            top_height = max(380, int(total_height * 0.58))
            bottom_height = max(240, total_height - top_height)
            self.bottom_widget.setMinimumHeight(220)
            self.bottom_widget.setMaximumHeight(16777215)
            self.main_splitter.setSizes([620, 360])
        self.run_splitter.setSizes([top_height, bottom_height])

    def closeEvent(self, event) -> None:  # noqa: N802
        """Cleanup module resources on app close."""
        if not self.orchestrator.shutdown():
            event.ignore()
            return
        self._hotkey_filter.close()
        self._task_pipe_server.stop()
        self._command_pipe_server.stop()
        self._overlay.hide_overlay()
        self.history_view.history_manager.close()
        super().closeEvent(event)


def _install_crash_hook() -> None:
    from orchestrator.crash_reporter import write_crash_dump as _write_crash_dump

    def _hook(exc_type, exc_value, exc_tb):
        _write_crash_dump(exc_value, run_id="main", phase="unhandled_exception")
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def main() -> int:
    """App entry point."""
    _install_crash_hook()
    startup_config = resolve_startup_config()
    startup_readiness = evaluate_startup_readiness(startup_config)

    app = QApplication(sys.argv)
    window = MainWindow(startup_readiness=startup_readiness)
    if startup_config.api_key and not _is_mock_startup(startup_config):
        window.start_async_preflight(startup_config)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
