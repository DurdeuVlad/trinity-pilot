"""Bridge between unified-app UI and Trinity Core."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal, Optional

try:
    from trinity_core.models import TaskInput, TaskResult
    from trinity_core.trinity import TrinityExecutor
    _TRINITY_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - runtime optional in packaged builds
    TaskInput = None
    TaskResult = Any
    TrinityExecutor = None
    _TRINITY_IMPORT_ERROR = exc

Domain = Literal["web", "desktop", "cli"]


class TrinityBridge:
    """Owns Trinity lifecycle and task execution for the desktop app."""

    def __init__(self) -> None:
        self.executor: Optional[Any] = None

    async def initialize(self) -> None:
        """Initialize a reusable executor instance."""
        if self.executor is None:
            if TrinityExecutor is None:
                if _TRINITY_IMPORT_ERROR is not None:
                    raise RuntimeError(
                        "Trinity Core is not available in this environment: "
                        f"{_TRINITY_IMPORT_ERROR}"
                    ) from _TRINITY_IMPORT_ERROR
                raise RuntimeError("Trinity Core is not available in this environment")
            self.executor = TrinityExecutor()
        await self.executor.initialize()

    def set_frame_callback(self, callback) -> None:
        """Forward a live-frame callback to the BrowserAdapter if available.

        Must be called after initialize() so that executor.adapters is populated.
        The callback receives raw JPEG bytes from the CDP screencast.
        """
        if self.executor is None:
            return
        browser_adapter = getattr(self.executor, "adapters", {}).get("web")
        if browser_adapter is not None and hasattr(browser_adapter, "set_frame_callback"):
            browser_adapter.set_frame_callback(callback)

    async def get_capabilities(self) -> dict:
        """Return the capability map of all initialized adapters."""
        if self.executor is None:
            return {}
        fn = getattr(self.executor, "get_capabilities_all", None)
        if callable(fn):
            try:
                return await fn()
            except Exception:
                return {}
        return {}

    async def execute_task(
        self,
        task_id: str,
        description: str,
        domain: Domain,
        context: Optional[dict] = None,
        expected_outcome: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        cancel_event: Any = None,
    ) -> Any:
        """Execute one task through Trinity Core."""
        if self.executor is None:
            raise RuntimeError("TrinityBridge is not initialized")
        available = getattr(self.executor, "adapters", {})
        if domain not in available:
            live = ", ".join(available.keys()) if available else "none"
            raise RuntimeError(
                f"Domain '{domain}' is not available (initialized adapters: {live}). "
                "Check that the backend is enabled in config."
            )
        if TaskInput is None:
            task = SimpleNamespace(
                task_id=task_id,
                description=description,
                domain=domain,
                context=context or {},
                expected_outcome=expected_outcome,
                timeout=timeout,
                max_retries=max_retries,
                cancel_event=cancel_event,
            )
        else:
            task = TaskInput(
                task_id=task_id,
                description=description,
                domain=domain,
                context=context or {},
                expected_outcome=expected_outcome,
                timeout=timeout,
                max_retries=3 if max_retries is None else max_retries,
                cancel_event=cancel_event,
            )
        return await self.executor.execute(task)

    async def shutdown(self) -> None:
        """Release executor resources."""
        if self.executor is not None:
            await self.executor.shutdown()
            self.executor = None

    async def close_browser_session(self, session_id: str) -> None:
        """Close a reusable browser session held by Trinity Core."""
        if self.executor is None:
            return
        close_browser_session = getattr(self.executor, "close_browser_session", None)
        if callable(close_browser_session):
            await close_browser_session(session_id)

    async def close_desktop_session(self, session_id: str) -> None:
        """Close a persistent desktop session subprocess."""
        if self.executor is None:
            return
        close_fn = getattr(self.executor, "close_desktop_session", None)
        if callable(close_fn):
            await close_fn(session_id)

    async def close_cli_session(self, session_id: str) -> None:
        """Close a persistent CLI backend session."""
        if self.executor is None:
            return
        close_fn = getattr(self.executor, "close_cli_session", None)
        if callable(close_fn):
            await close_fn(session_id)
