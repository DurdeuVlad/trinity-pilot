"""Bridge between unified-app UI and Trinity Core."""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Literal, Optional

from .settings_manager import SettingsManager

try:
    from trinity_core.models import TaskInput, TaskResult
    from trinity_core.trinity import TrinityExecutor
    _TRINITY_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - runtime optional in packaged builds
    TaskInput = None
    TaskResult = Any
    TrinityExecutor = None
    _TRINITY_IMPORT_ERROR = exc

Domain = str


class TrinityBridge:
    """Owns the desktop-to-Core handoff for finalized objectives."""

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
            try:
                self.executor = TrinityExecutor()
            except Exception as exc:
                if "GEMINI_API_KEY" in str(exc):
                    raise RuntimeError(
                        "Trinity Core execution requires GEMINI_API_KEY. Set it in unified-app/.env"
                    ) from exc
                if "OPENAI_API_KEY" in str(exc):
                    raise RuntimeError(
                        "Trinity Core execution requires GEMINI_API_KEY (not OpenAI). Set it in unified-app/.env"
                    ) from exc
                raise
        await self.executor.initialize()

    async def get_capabilities(self) -> dict:
        """Return the capability map of all Core-visible MCP targets."""
        if self.executor is None:
            return {}
        fn = getattr(self.executor, "get_capabilities_all", None)
        if callable(fn):
            try:
                return await fn()
            except Exception:
                return {}
        return {}

    def suggest_domain(self, description: str) -> str:
        """Suggest a domain based on description keywords using core registry."""
        if self.executor is None or not self.executor.initialized:
            # Coarse fallback if not initialized
            lowered = description.lower()
            if any(t in lowered for t in ("browser", "url", "http")): return "web"
            if any(t in lowered for t in ("window", "app")): return "desktop"
            return "cli"
        
        try:
            return self.executor.strategy_registry.suggest_domain(description)
        except Exception:
            return "cli"

    async def execute_task(
        self,
        task_id: str,
        description: str,
        domain: Domain,
        context: Optional[dict] = None,
        target_server: Optional[str] = None,
        objective_steps: Optional[list[str]] = None,
        expected_outcome: Optional[str] = None,
        verification_checks: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        cancel_event: Any = None,
    ) -> Any:
        """Execute one finalized desktop task through Trinity Core."""
        if self.executor is None:
            raise RuntimeError("TrinityBridge is not initialized")
        merged_context = dict(context or {})
        if target_server:
            merged_context.setdefault("target_server", target_server)
            merged_context.setdefault("selected_mcp_server", target_server)
        if TaskInput is None:
            task = SimpleNamespace(
                task_id=task_id,
                description=description,
                domain=domain,
                context=merged_context,
                target_server=target_server,
                objective_steps=objective_steps or [],
                expected_outcome=expected_outcome,
                verification_checks=verification_checks or [],
                timeout=timeout,
                max_retries=max_retries,
                cancel_event=cancel_event,
            )
        else:
            task = TaskInput(
                task_id=task_id,
                description=description,
                domain=domain,
                context=merged_context,
                target_server=target_server,
                objective_steps=objective_steps or [],
                expected_outcome=expected_outcome,
                verification_checks=verification_checks or [],
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
