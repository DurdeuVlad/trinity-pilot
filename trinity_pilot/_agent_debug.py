"""Session debug NDJSON logger — thin wrapper over telemetry.trace."""
from __future__ import annotations

from trinity_pilot.telemetry.trace import emit


def agent_dbg(
    location: str,
    message: str,
    data: dict | None = None,
    *,
    hypothesis_id: str = "",
    run_id: str = "probe",
) -> None:
    # #region agent log
    emit(location, message, data, hypothesis_id=hypothesis_id, run_id=run_id)
    # #endregion
