"""Bridge between unified-app UI and Trinity Core."""
from __future__ import annotations

import asyncio
import logging
import os
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Optional

from .settings_manager import SettingsManager

logger = logging.getLogger(__name__)

try:
    from trinity_core.models import TaskInput, TaskResult
    from trinity_core.trinity import ObjectiveOrchestrator
    _TRINITY_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - runtime optional in packaged builds
    TaskInput = None
    TaskResult = Any
    ObjectiveOrchestrator = None
    _TRINITY_IMPORT_ERROR = exc

Domain = str

_BRIDGE_WEB_HINTS = (
    "browser", "website", "url", "http", "https",
    "google", "github", "wikipedia", "wiki", "site",
    "page", "pagina", "pagină", "cauta", "caută", "caut",
    "search", "navigate", "open link", "visit", "look up",
    "find online", "web", "online", "internet",
)
_BRIDGE_DESKTOP_HINTS = (
    "notepad", "window", "desktop", "application",
    "fereastra", "fereastră", "calculator", "excel",
    "word", "explorer", "paint", "settings", "launch",
    "open app", "task manager", "control panel",
)


class TrinityBridge:
    """Owns the desktop-to-Core handoff for finalized objectives."""

    def __init__(self, *, use_subprocess: bool = False) -> None:
        self.executor: Optional[Any] = None
        self.use_subprocess = use_subprocess
        self._registry_enriched = False

    async def initialize(self) -> None:
        """Initialize a reusable executor instance."""
        if self.executor is None:
            if ObjectiveOrchestrator is None:
                if _TRINITY_IMPORT_ERROR is not None:
                    raise RuntimeError(
                        "Trinity Core is not available in this environment: "
                        f"{_TRINITY_IMPORT_ERROR}"
                    ) from _TRINITY_IMPORT_ERROR
                raise RuntimeError("Trinity Core is not available in this environment")
            try:
                self._apply_saved_api_keys()
                self.executor = ObjectiveOrchestrator()
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

        # Enrich registry from live server capability resources (parallel, non-fatal).
        # Guard prevents re-enrichment on repeated initialize() calls on the same bridge instance.
        if not self._registry_enriched and hasattr(self.executor, "strategy_registry"):
            self._registry_enriched = True
            enrichment = await self.executor.strategy_registry.enrich_all(timeout_per_server=10.0)
            failed = [k for k, ok in enrichment.items() if not ok]
            if failed:
                logger.warning(
                    "Capability enrichment skipped for servers not reachable at init: %s",
                    ", ".join(failed),
                )

    def _apply_saved_api_keys(self) -> None:
        settings = SettingsManager().load()
        for env_name, setting_name in (
            ("OPENAI_API_KEY", "openai_api_key"),
            ("GEMINI_API_KEY", "gemini_api_key"),
        ):
            if os.getenv(env_name):
                continue
            value = str(settings.get(setting_name) or "").strip()
            if value:
                os.environ[env_name] = value

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

    def suggest_server_for_objective(self, objective: str) -> str:
        """Return the best strategy_id for a single objective string.

        Uses the initialized executor's strategy registry (full keyword + example scoring).
        Falls back to coarse hint matching mapped to server IDs if executor not ready.
        """
        if self.executor is not None and self.executor.initialized:
            try:
                return self.executor.strategy_registry.suggest_strategy_for_objective(objective)
            except Exception:
                pass
        lowered = objective.lower()
        if any(t in lowered for t in _BRIDGE_WEB_HINTS):
            return "browser_mcp"
        if any(t in lowered for t in _BRIDGE_DESKTOP_HINTS):
            return "desktop_mcp"
        return "cli_mcp"

    def server_domain_map(self) -> dict[str, str]:
        """Return {strategy_id: domain} built from the live registry.

        Returns empty dict if bridge not yet initialized; caller falls back to
        the static _SERVER_TO_DOMAIN constant.
        """
        if self.executor is None or not self.executor.initialized:
            return {}
        try:
            return {
                s.strategy_id: s.domain
                for s in self.executor.strategy_registry.list()
            }
        except Exception:
            return {}

    def known_servers(self) -> list[dict[str, str]]:
        """Return [{strategy_id, domain, display_name}] for all registered strategies.

        Returns empty list if bridge not initialized.
        """
        if self.executor is None or not self.executor.initialized:
            return []
        try:
            return [
                {
                    "strategy_id": s.strategy_id,
                    "domain": s.domain,
                    "display_name": s.display_name,
                }
                for s in self.executor.strategy_registry.list()
            ]
        except Exception:
            return []

    def suggest_domain(self, description: str) -> str:
        """Suggest a domain based on description keywords using core registry."""
        if self.executor is None or not self.executor.initialized:
            lowered = description.lower()
            if any(t in lowered for t in _BRIDGE_WEB_HINTS):
                return "web"
            if any(t in lowered for t in _BRIDGE_DESKTOP_HINTS):
                return "desktop"
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
        sub_objectives: Optional[list[str]] = None,
        expected_outcome: Optional[str] = None,
        verification_checks: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        cancel_event: Any = None,
    ) -> Any:
        """Execute one finalized desktop task through Trinity Core."""
        if self.use_subprocess and os.getenv("TRINITY_INPROCESS_BRIDGE") != "1":
            return await self._execute_task_subprocess(
                task_id=task_id,
                description=description,
                domain=domain,
                context=context,
                target_server=target_server,
                sub_objectives=sub_objectives,
                expected_outcome=expected_outcome,
                verification_checks=verification_checks,
                timeout=timeout,
                max_retries=max_retries,
            )
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
                sub_objectives=sub_objectives or [],
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
                sub_objectives=sub_objectives or [],
                expected_outcome=expected_outcome,
                verification_checks=verification_checks or [],
                timeout=timeout,
                max_retries=3 if max_retries is None else max_retries,
                cancel_event=cancel_event,
            )
        return await self.executor.execute(task)

    async def _execute_task_subprocess(
        self,
        *,
        task_id: str,
        description: str,
        domain: Domain,
        context: Optional[dict],
        target_server: Optional[str],
        sub_objectives: Optional[list[str]],
        expected_outcome: Optional[str],
        verification_checks: Optional[list[dict[str, Any]]],
        timeout: Optional[int],
        max_retries: Optional[int],
    ) -> Any:
        runner = Path(__file__).with_name("trinity_subprocess_runner.py")
        payload = {
            "task_id": task_id,
            "description": description,
            "domain": domain,
            "context": context or {},
            "target_server": target_server,
            "sub_objectives": sub_objectives or [],
            "expected_outcome": expected_outcome,
            "verification_checks": verification_checks or [],
            "timeout": timeout,
            "max_retries": 3 if max_retries is None else max_retries,
        }
        proc_timeout = float(timeout or 600) + 30.0

        def _run() -> dict[str, Any]:
            completed = subprocess.run(
                [sys.executable, str(runner)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=proc_timeout,
                cwd=str(Path(__file__).resolve().parents[1]),
                env=os.environ.copy(),
            )
            stdout = (completed.stdout or "").strip()
            envelope = None
            for line in stdout.splitlines():
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict) and "ok" in candidate:
                    envelope = candidate
            if envelope is None:
                raise RuntimeError(
                    "Trinity subprocess returned non-JSON output. "
                    f"exit={completed.returncode}; stdout={stdout[-1000:]}; stderr={(completed.stderr or '')[-1000:]}"
                )
            if completed.returncode != 0 or not envelope.get("ok"):
                raise RuntimeError(
                    str(envelope.get("error") or "Trinity subprocess failed")
                    + (f"\n{envelope.get('traceback')}" if envelope.get("traceback") else "")
                )
            result = envelope.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Trinity subprocess returned an invalid result payload.")
            return result

        return await asyncio.to_thread(_run)

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
