"""Executor telemetry event emitter for trinity_core (TC-S5)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

TASK_STARTED = "task_started"
TASK_SUCCEEDED = "task_succeeded"
TASK_FAILED = "task_failed"
TASK_CANCELLED = "task_cancelled"

# ---------------------------------------------------------------------------
# Redaction utility
# ---------------------------------------------------------------------------

# Patterns that indicate likely secrets in dict keys.
_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|token|credential|auth)",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of payload with secret-like fields redacted."""
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if _SECRET_KEY_PATTERN.search(str(key)):
            result[key] = _REDACTED
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Collector interface and in-memory collector
# ---------------------------------------------------------------------------

EventCollector = Callable[[str, dict[str, Any]], None]

_collectors: list[EventCollector] = []


def register_collector(collector: EventCollector) -> None:
    """Register an event collector callable."""
    _collectors.append(collector)


def unregister_collector(collector: EventCollector) -> None:
    """Unregister a previously registered event collector."""
    try:
        _collectors.remove(collector)
    except ValueError:
        pass


class InMemoryCollector:
    """Fake collector that stores events in memory for testing."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append({"event_type": event_type, **payload})


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------

def emit_event(event_type: str, payload: dict[str, Any]) -> None:
    """Emit a lifecycle event to all registered collectors after redaction."""
    safe = redact_payload(payload)
    safe["event_type"] = event_type
    for collector in list(_collectors):
        try:
            collector(event_type, {k: v for k, v in safe.items() if k != "event_type"})
        except Exception:
            pass  # Never let a collector failure propagate into task execution


def make_event_payload(
    *,
    task_id: str,
    domain: str,
    adapter_name: str,
    duration_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical event payload with required fields."""
    payload: dict[str, Any] = {
        "task_id": task_id,
        "domain": domain,
        "adapter_name": adapter_name,
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 2)
    if extra:
        payload.update(extra)
    return payload
