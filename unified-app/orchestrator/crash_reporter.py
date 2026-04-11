"""Standalone crash dump writer.

Intentionally has no imports from the rest of the app so it can be called
safely from any exception boundary — orchestrator worker thread, sys.excepthook,
audit recording failures — without risk of circular imports or secondary errors.
"""
from __future__ import annotations

import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_CRASH_DIR = Path(__file__).resolve().parents[1] / "_runtime" / "crash_reports"


def write_crash_dump(
    exc: BaseException,
    *,
    run_id: str = "unknown",
    task_description: str = "",
    phase: str = "unknown",
) -> str | None:
    """Write a plain-text crash dump to ``_runtime/crash_reports/``.

    Returns the path to the written file, or ``None`` if writing failed.
    Safe to call from any exception handler — never raises.
    """
    try:
        _CRASH_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d_%H%M%S")
        run_short = str(run_id)[:12].replace("/", "-").replace("\\", "-")
        filename = f"{ts_str}_{run_short}.md"
        path = _CRASH_DIR / filename

        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_text = "".join(tb_lines).rstrip()

        task_line = task_description[:200] if task_description else "(none)"

        lines = [
            "# TrinityPilot Crash Report",
            "",
            f"**Timestamp (UTC):** {ts.isoformat()}",
            f"**Run ID:** {run_id}",
            f"**Phase:** {phase}",
            f"**Exception type:** `{type(exc).__name__}`",
            f"**Exception message:** {str(exc)[:500]}",
            "",
            "## Task",
            "",
            task_line,
            "",
            "## Traceback",
            "",
            "```",
            tb_text,
            "```",
            "",
            "## Environment",
            "",
            f"- Python: {sys.version}",
            f"- Platform: {platform.platform()}",
            f"- Executable: {sys.executable}",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)
    except Exception:
        return None
