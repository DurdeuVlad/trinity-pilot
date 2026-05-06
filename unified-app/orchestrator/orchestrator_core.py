"""Unified app -> Trinity Core objective handoff path."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from orchestrator.database import TaskStatus

logger = logging.getLogger(__name__)

# Domain → (resolved_domain, target_server) mapping
_DOMAIN_TARGETS: dict[str, tuple[str, str]] = {
    "cli": ("cli", "cli_mcp"),
    "web": ("web", "browser_mcp"),
    "browser": ("web", "browser_mcp"),
    "desktop": ("desktop", "desktop_mcp"),
    "mixed": ("mixed", ""),
}
_DEFAULT_TARGET = ("mixed", "")


def _resolve_domain(domain: str) -> tuple[str, str]:
    return _DOMAIN_TARGETS.get(domain.lower(), _DEFAULT_TARGET)


class HistoryManager:
    """Default no-op history manager. Replace in tests via monkeypatch."""

    def create_task(self, *args: Any, **kwargs: Any) -> None:
        pass

    def start_task(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_sub_objective(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update_step_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def complete_task(self, *args: Any, **kwargs: Any) -> None:
        pass


def get_event_bus():
    from event_bus import get_event_bus as _get
    return _get()


# TrinityBridge import — monkeypatched in tests
from orchestrator.trinity_bridge import TrinityBridge  # noqa: E402


class UnifiedAppObjectiveRunner:
    """Async app-side runner: submits objectives to Trinity Core."""

    def __init__(
        self,
        description: str,
        domain: str,
        *,
        approved_plan: Optional[list[str]] = None,
    ) -> None:
        self.description = description
        self.domain = domain
        self.approved_plan = approved_plan or []
        self.task_id = f"run_{uuid.uuid4().hex[:12]}"

    async def _execute(self) -> None:
        resolved_domain, target_server = _resolve_domain(self.domain)
        history = HistoryManager()
        bus = get_event_bus()

        history.create_task(self.task_id, description=self.description, domain=resolved_domain)
        history.start_task(self.task_id)

        bridge = TrinityBridge()
        try:
            await bridge.initialize()

            result = await bridge.execute_task(
                task_id=self.task_id,
                description=self.description,
                domain=resolved_domain,
                target_server=target_server or None,
                sub_objectives=self.approved_plan,
            )

            payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            success = payload.get("status") == "success"
            meta = payload.get("metadata") or {}
            output = str(meta.get("output") or payload.get("error") or payload.get("status") or "")

            for i, sub_obj in enumerate(self.approved_plan, start=1):
                history.update_step_status(
                    self.task_id,
                    i,
                    TaskStatus.COMPLETED if success else TaskStatus.FAILED,
                    result_data=output,
                )

            history.complete_task(
                self.task_id,
                result_data=output or ("Task completed." if success else "Task failed."),
                error_message=None if success else output,
                status=TaskStatus.COMPLETED,
            )

            bus.execution_complete.emit({
                "status": "success" if success else "failure",
                "target_server": target_server,
                "domain": resolved_domain,
                "output": output,
                "task_id": self.task_id,
            })

        except Exception as exc:
            logger.exception("UnifiedAppObjectiveRunner execution failed: %s", exc)
            history.complete_task(
                self.task_id,
                error_message=str(exc),
                status=TaskStatus.FAILED,
            )
            bus.execution_complete.emit({
                "status": "failure",
                "target_server": target_server,
                "domain": resolved_domain,
                "error": str(exc),
                "task_id": self.task_id,
            })
            raise
        finally:
            await bridge.shutdown()
