"""Debug-mode NDJSON logger for VM probe runs — thin wrapper over telemetry.trace."""
from __future__ import annotations

from trinity_pilot.telemetry.trace import emit


def dbg(
    location: str,
    message: str,
    data: dict | None = None,
    hypothesis_id: str = "",
    run_id: str = "",
) -> None:
    del hypothesis_id
    emit(location, message, data, run_id=run_id)
