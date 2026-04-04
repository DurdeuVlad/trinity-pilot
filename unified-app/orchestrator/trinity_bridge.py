"""Bridge between unified-app UI and Trinity Core."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal, Optional

try:
    from trinity_core.models import TaskInput, TaskResult
    from trinity_core.trinity import TrinityExecutor
except ModuleNotFoundError:  # pragma: no cover - runtime optional in packaged builds
    TaskInput = None
    TaskResult = Any
    TrinityExecutor = None

Domain = Literal["web", "desktop", "cli"]


class TrinityBridge:
    """Owns Trinity lifecycle and task execution for the desktop app."""

    def __init__(self) -> None:
        self.executor: Optional[Any] = None

    async def initialize(self) -> None:
        """Initialize a reusable executor instance."""
        if self.executor is None:
            if TrinityExecutor is None:
                raise RuntimeError("Trinity Core is not available in this environment")
            self.executor = TrinityExecutor()
        await self.executor.initialize()

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
