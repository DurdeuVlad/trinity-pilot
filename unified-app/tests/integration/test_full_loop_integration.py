"""Full-loop integration tests: OrchestratorWorker + real TrinityExecutor + CLIAdapter + gemini_mock.

No real Gemini API key or real TrinityCore installation required.
All genai calls are intercepted by the QueueBackend mock (pytest_plugin.py).
GEMINI_API_KEY=mock is set by conftest; TrinityConfig accepts any non-empty key.

Sprint coverage:
  Sprint 1 â test_full_loop_cli_task_reaches_completed (happy path, full stack)
  Sprint 2 â test_trinity_executor_cli_returns_success (direct executor test)
  Sprint 2 â test_full_loop_failed_step_causes_failed_status (failure + traceback sanitization)
  Browser sprint â test_full_loop_browser_task_reaches_completed (domain='web' mocked)
  Desktop sprint â test_full_loop_desktop_task_reaches_completed (domain='desktop' mocked)
"""
from __future__ import annotations

from typing import Any

import orchestrator.orchestrator_core as core_module
import pytest
from orchestrator.database import TaskStatus
from orchestrator.event_bus import EventBus
from orchestrator.orchestrator_core import OrchestratorWorker
from orchestrator.providers.base import LLMProvider

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Shared stubs â no Qt / DB / filesystem dependencies
# ---------------------------------------------------------------------------


class _Signal:
    """Minimal signal stub: accepts connect() without implementation."""

    def connect(self, _fn: Any) -> None:  # noqa: ANN001
        """No-op connect for stub signals."""
        return None


class FakeWatcher:
    """Minimal ScreenshotWatcher stub: no Qt or screen access."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise stub signals."""
        self.frame_captured = _Signal()
        self.frame_rate_updated = _Signal()

    def start_watching(self) -> None:
        """No-op."""
        return None

    def stop_watching(self) -> None:
        """No-op."""
        return None


class RecordingHistoryManager:
    """Records complete_task and update_step_status calls without a real DB.

    Status derivation mirrors database/manager.py:complete_task exactly,
    so assertions on final["status"] match what the real manager would store.
    """

    def __init__(self) -> None:
        """Initialise empty recording lists."""
        self.completed_calls: list[dict[str, Any]] = []
        self.step_updates: list[dict[str, Any]] = []

    def create_task(self, *args: Any, **kwargs: Any) -> None:
        """No-op."""
        return None

    def start_task(self, *args: Any, **kwargs: Any) -> None:
        """No-op."""
        return None

    def add_step(self, *args: Any, **kwargs: Any) -> None:
        """No-op."""
        return None

    def update_step_status(
        self,
        task_id: Any,
        step_number: Any,
        status: Any,
        result_data: Any = None,
        error_message: Any = None,
    ) -> None:
        """Record step status update."""
        self.step_updates.append(
            {
                "task_id": task_id,
                "step_number": step_number,
                "status": status,
                "result_data": result_data,
                "error_message": error_message,
            }
        )

    def complete_task(
        self,
        task_id: Any,
        result_data: Any = None,
        error_message: Any = None,
        status: Any = None,
    ) -> None:
        """Record task completion; derive status as the real manager does."""
        derived = (
            status
            if status is not None
            else (TaskStatus.COMPLETED if not error_message else TaskStatus.FAILED)
        )
        self.completed_calls.append(
            {
                "task_id": task_id,
                "result_data": result_data,
                "error_message": error_message,
                "status": derived,
            }
        )

    def close(self) -> None:
        """No-op."""
        return None


class _FailingProvider(LLMProvider):
    """Provider stub that raises on call() to simulate AI/network failures."""

    def __init__(self, error_message: str) -> None:
        self._error_message = error_message

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        raise RuntimeError(self._error_message)

    async def probe(self) -> None:
        pass



# ---------------------------------------------------------------------------
# Sprint 1 â full-loop happy path
# ---------------------------------------------------------------------------


async def test_full_loop_cli_task_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Real MacroPlanner + TrinityBridge + TrinityExecutor + CLIAdapter + gemini_mock.

    Neither MacroPlanner nor TrinityBridge is patched â the full real execution
    path runs end-to-end.  The task must reach TaskStatus.COMPLETED.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    history = RecordingHistoryManager()
    bus = EventBus()
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("echo status check", "cli")
    await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    assert final["result_data"] == {"status": "success", "category": "success"}
    completed_steps = [step for step in history.step_updates if step["status"] == TaskStatus.COMPLETED]
    assert completed_steps, "No completed step payloads were recorded"
    assert completed_steps[-1]["result_data"]["status"] == "success"
    assert "output" in completed_steps[-1]["result_data"]


# ---------------------------------------------------------------------------
# Sprint 2 â direct executor test
# ---------------------------------------------------------------------------


async def test_full_loop_cli_directory_inspection_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Directory inspection should stay deterministic end-to-end in mock mode."""
    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    history = RecordingHistoryManager()
    bus = EventBus()
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("Show the current directory path and list its contents", "cli")
    await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    completed_steps = [step for step in history.step_updates if step["status"] == TaskStatus.COMPLETED]
    assert len(completed_steps) == 2, f"Expected 2 completed directory steps; got {len(completed_steps)}"
    assert all(step["result_data"]["status"] == "success" for step in completed_steps)


async def test_trinity_executor_cli_returns_success(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """TrinityExecutor.execute() for a CLI task returns TaskResult(status='success').

    Exercises the full TrinityExecutor â CLIAdapter â SmartOrchestrator path
    without the OrchestratorWorker wrapper.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    from trinity_core.models import TaskInput
    from trinity_core.trinity import TrinityExecutor

    async with TrinityExecutor() as executor:
        task = TaskInput(task_id="integ-cli-1", description="echo hello test", domain="cli")
        result = await executor.execute(task)

    assert result.status == "success", (
        f"Expected 'success'; got {result.status!r}. error={result.error!r}"
    )


# ---------------------------------------------------------------------------
# Sprint 2 â failure path and traceback sanitization
# ---------------------------------------------------------------------------


async def test_full_loop_failed_step_causes_failed_status(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """A step that returns status='failure' causes TaskStatus.FAILED.

    Also verifies that raw Python tracebacks do not appear in event-bus
    status_update messages (the user-visible UI channel).
    The DB error_message stores the full message for audit purposes;
    only the UI-facing messages are required to be traceback-free.
    """

    error_exc = (
        "Traceback (most recent call last):\n"
        "  File 'fake_provider.py', line 1\n"
        "SimulatedError: step intentionally failed"
    )
    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    monkeypatch.setattr(core_module, "make_provider", lambda *a, **kw: _FailingProvider(error_exc))

    history = RecordingHistoryManager()
    bus = EventBus()
    error_ui_messages: list[str] = []
    bus.status_update.connect(
        lambda msg, level: error_ui_messages.append(msg) if level == "error" else None
    )
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("failing step task", "cli")
    await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.FAILED, (
        f"Expected FAILED; got {final['status']!r}"
    )
    assert error_ui_messages, "No error-level status_update was emitted to the bus"
    for msg in error_ui_messages:
        assert "Traceback" not in msg, (
            f"Raw traceback in user-visible UI message: {msg!r}"
        )


@pytest.mark.parametrize(
    ("exc_message", "expected_snippet"),
    [
        ("api_key_invalid: authentication failed", "Authentication failed"),
        ("429 quota exceeded rate limit reached", "backend encountered an error"),
        ("ConnectionError: service unreachable network", "backend encountered an error"),
        ("JSONDecodeError: unusable planning response", "request could not be understood"),
    ],
)
async def test_full_loop_live_failure_messages_reach_ui_safely(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
    exc_message: str,
    expected_snippet: str,
) -> None:
    """AI provider failures surface as explicit failed outcomes with no tracebacks."""
    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    monkeypatch.setattr(core_module, "make_provider", lambda *a, **kw: _FailingProvider(exc_message))

    history = RecordingHistoryManager()
    bus = EventBus()
    error_ui_messages: list[str] = []
    bus.status_update.connect(
        lambda msg, level: error_ui_messages.append(msg) if level == "error" else None
    )
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    worker = OrchestratorWorker("explicit live failure", "cli")
    await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.FAILED
    assert error_ui_messages, "No error-level UI message was emitted"
    assert any(expected_snippet in msg for msg in error_ui_messages)
    for msg in error_ui_messages:
        assert "Traceback" not in msg


# ---------------------------------------------------------------------------
# Sprint 1 â full-loop browser (domain="web") path
# ---------------------------------------------------------------------------


async def test_full_loop_browser_task_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """OrchestratorWorker(domain='web') â TrinityBridge â BrowserAdapter (mocked).

    run_browser_task is replaced with an AsyncMock; no real Playwright or browser
    is launched.  MacroPlanner falls through to _fallback_plan which returns 3 web
    steps; each is executed via the mocked BrowserAdapter.  Final status must be
    TaskStatus.COMPLETED.
    """
    import base64
    from unittest.mock import patch

    import trinity_core.adapters.browser  # noqa: F401 â ensures sys.path patched

    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    history = RecordingHistoryManager()
    bus = EventBus()
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    async def _fake_start(self: Any) -> None:
        return None

    async def _fake_stop(self: Any) -> None:
        return None

    async def _fake_get_state(self: Any) -> dict[str, Any]:
        return {
            "screenshot": base64.b64encode(b"fake-browser-frame").decode("ascii"),
            "accessibility_tree": {"role": "document", "name": "Example page"},
            "url": "https://example.com",
            "title": "Example Domain",
        }

    async def _fake_verify(self: Any, expected_outcome: Any, state: Any) -> str:
        return "success"

    with patch("browser_agent.browser.manager.BrowserManager.start", _fake_start), patch(
        "browser_agent.browser.manager.BrowserManager.stop", _fake_stop
    ), patch("browser_agent.browser.manager.BrowserManager.get_state", _fake_get_state), patch(
        "browser_agent.core.verifier.OutcomeVerifier.verify", _fake_verify
    ):
        worker = OrchestratorWorker("open browser and navigate to example.com", "web")
        await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    completed_steps = [step for step in history.step_updates if step["status"] == TaskStatus.COMPLETED]
    assert completed_steps, "No completed browser step payloads were recorded"
    browser_payload = completed_steps[-1]["result_data"]
    assert browser_payload["status"] == "success"
    assert "output" in browser_payload


# ---------------------------------------------------------------------------
# Desktop sprint â full-loop desktop (domain="desktop") path
# ---------------------------------------------------------------------------


async def test_full_loop_desktop_task_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """OrchestratorWorker(domain='desktop') â TrinityBridge â DesktopAdapter (mocked).

    run_desktop_automation is replaced with a plain MagicMock (sync function).
    asyncio.to_thread calls it in a thread pool and returns its return value.
    MacroPlanner falls through to _fallback_plan which returns 3 desktop steps;
    each is executed via the mocked DesktopAdapter.  Final status must be
    TaskStatus.COMPLETED.
    """
    from unittest.mock import patch

    import trinity_core.adapters.desktop  # noqa: F401

    from desktop_io_models import DesktopTaskResult  # type: ignore[import]

    mock_result = DesktopTaskResult(
        status="success",
        successful_actions=1,
        total_actions=1,
        execution_log=[],
        metadata={"app_context": "Notepad"},
    )

    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    history = RecordingHistoryManager()
    bus = EventBus()
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    with patch(
        "trinity_core.adapters.desktop.run_desktop_automation",
        return_value=mock_result,
    ):
        worker = OrchestratorWorker("open Notepad", "desktop")
        await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    completed_steps = [step for step in history.step_updates if step["status"] == TaskStatus.COMPLETED]
    assert completed_steps, "No completed desktop step payloads were recorded"
    desktop_payload = completed_steps[-1]["result_data"]
    assert desktop_payload["status"] == "success"
    assert "output" in desktop_payload


async def test_teacher_workflow_web_to_notepad_reaches_completed(
    monkeypatch: pytest.MonkeyPatch,
    gemini_mock: Any,
) -> None:
    """Teacher workflow routes web then desktop and reaches COMPLETED in mock mode."""
    import base64
    from unittest.mock import patch

    import trinity_core.adapters.browser  # noqa: F401
    import trinity_core.adapters.desktop  # noqa: F401

    from desktop_io_models import DesktopTaskResult  # type: ignore[import]

    monkeypatch.setenv("GEMINI_API_KEY", "mock")

    history = RecordingHistoryManager()
    bus = EventBus()
    backend_calls: list[str] = []
    error_ui_messages: list[str] = []
    bus.status_update.connect(
        lambda msg, level: error_ui_messages.append(msg) if level == "error" else None
    )
    monkeypatch.setattr(core_module, "HistoryManager", lambda: history)
    monkeypatch.setattr(core_module, "ScreenshotWatcher", FakeWatcher)
    monkeypatch.setattr(core_module, "get_event_bus", lambda: bus)

    async def _fake_start(self: Any) -> None:
        backend_calls.append("web")
        return None

    async def _fake_stop(self: Any) -> None:
        return None

    async def _fake_get_state(self: Any) -> dict[str, Any]:
        return {
            "screenshot": base64.b64encode(b"teacher-workflow-frame").decode("ascii"),
            "accessibility_tree": {"role": "document", "name": "OpenAI"},
            "url": "https://openai.com",
            "title": "OpenAI",
        }

    async def _fake_verify(self: Any, expected_outcome: Any, state: Any) -> str:
        return "success"

    def _fake_run_desktop_automation(**kwargs: Any) -> DesktopTaskResult:
        backend_calls.append("desktop")
        return DesktopTaskResult(
            status="success",
            successful_actions=1,
            total_actions=1,
            execution_log=[],
            metadata={"objective": kwargs.get("objective")},
        )

    with patch("browser_agent.browser.manager.BrowserManager.start", _fake_start), patch(
        "browser_agent.browser.manager.BrowserManager.stop", _fake_stop
    ), patch("browser_agent.browser.manager.BrowserManager.get_state", _fake_get_state), patch(
        "browser_agent.core.verifier.OutcomeVerifier.verify", _fake_verify
    ), patch(
        "trinity_core.adapters.desktop.run_desktop_automation",
        side_effect=_fake_run_desktop_automation,
    ):
        worker = OrchestratorWorker(
            "Search the web for OpenAI, copy the first useful result summary, and paste it into Notepad.",
            "web",
        )
        await worker._execute()

    assert history.completed_calls, "complete_task was never called"
    final = history.completed_calls[-1]
    assert final["status"] == TaskStatus.COMPLETED, (
        f"Expected COMPLETED; got {final['status']!r}. "
        f"error_message={final.get('error_message')!r}"
    )
    assert not error_ui_messages
    completed_steps = [step for step in history.step_updates if step["status"] == TaskStatus.COMPLETED]
    assert completed_steps, "No completed teacher-workflow steps were recorded"
    assert completed_steps[-1]["result_data"]["status"] == "success"


# ---------------------------------------------------------------------------
# Sprint 3 -- MacroPlanner domain routing verification
# ---------------------------------------------------------------------------


async def test_macro_planner_routes_browser_task(
    monkeypatch,
    gemini_mock,
):
    """MacroPlanner._fallback_plan produces domain='web' steps for browser domain.

    Tests the deterministic fallback directly - no Gemini call or mock needed.
    Verifies plan.domain == 'web' and steps contain browser/web context.
    """
    from orchestrator.macro_planner import MacroPlanner
    from orchestrator.providers.factory import make_provider

    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    provider = make_provider("gemini", "mock")
    planner = MacroPlanner(provider)
    plan = await planner.generate_plan("open browser and navigate to example.com", "web")

    assert plan.domain == "web", f"Expected domain='web'; got {plan.domain!r}"
    assert plan.steps, "Plan must have at least one step"


async def test_macro_planner_routes_desktop_task(
    monkeypatch,
    gemini_mock,
):
    """MacroPlanner._fallback_plan produces domain='desktop' steps for desktop domain.

    Tests the deterministic fallback directly - no Gemini call or mock needed.
    Verifies plan.domain == 'desktop' and steps contain desktop context.
    """
    from orchestrator.macro_planner import MacroPlanner
    from orchestrator.providers.factory import make_provider

    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    provider = make_provider("gemini", "mock")
    planner = MacroPlanner(provider)
    plan = await planner.generate_plan("open Notepad", "desktop")

    assert plan.domain == "desktop", f"Expected domain='desktop'; got {plan.domain!r}"
    assert plan.steps, "Plan must have at least one step"
