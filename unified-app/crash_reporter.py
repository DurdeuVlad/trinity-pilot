"""Crash reporter — writes markdown crash dumps to _runtime/crash_reports/."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_REPORT_DIR = Path(__file__).parent / "_runtime" / "crash_reports"


def write_crash_dump(
    exc: BaseException,
    *,
    run_id: str = "unknown",
    phase: str = "unknown",
    task: str = "",
) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    ts_file = ts.strftime("%Y-%m-%d_%H%M%S")
    filename = _REPORT_DIR / f"{ts_file}_{run_id}.md"

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    lines = [
        "# TrinityPilot Crash Report",
        "",
        f"**Timestamp (UTC):** {ts.isoformat()}",
        f"**Run ID:** {run_id}",
        f"**Phase:** {phase}",
        f"**Exception type:** `{type(exc).__name__}`",
        f"**Exception message:** {exc}",
        "",
    ]

    if task:
        lines += ["## Task", "", task, ""]

    lines += [
        "## Traceback",
        "",
        "```",
        tb.rstrip(),
        "```",
        "",
        "## Environment",
        "",
        f"- Python: {sys.version}",
        f"- Platform: {sys.platform}",
        f"- Executable: {sys.executable}",
    ]

    filename.write_text("\n".join(lines), encoding="utf-8")
    return filename


def install_excepthook() -> None:
    """Replace sys.excepthook so unhandled main-thread exceptions get logged."""
    _original = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        try:
            write_crash_dump(exc_value, run_id="main", phase="unhandled_exception")
        except Exception:
            pass
        _original(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
