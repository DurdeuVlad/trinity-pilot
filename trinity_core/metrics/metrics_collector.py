"""Thread-safe metrics collector for trinity_core.

Records task, tool-call, LLM-call, and review events to a daily JSONL file
at ``{base_dir}/{YYYY-MM-DD}.jsonl``.  A process-wide singleton is accessible
via :func:`get_collector`.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_lock = threading.Lock()
_instance: Optional["MetricsCollector"] = None


def get_collector(base_dir: str | Path = ".metrics") -> "MetricsCollector":
    """Return the process-wide MetricsCollector singleton."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = MetricsCollector(base_dir)
    return _instance


class MetricsCollector:
    """Persist execution metrics to a daily JSONL file.

    All public ``record_*`` methods are thread-safe.

    Parameters
    ----------
    base_dir:
        Directory where metric files are written.  Created on first write.
    """

    def __init__(self, base_dir: str | Path = ".metrics") -> None:
        self._base_dir = Path(base_dir)
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public record methods
    # ------------------------------------------------------------------

    def record_task(
        self,
        task_id: str,
        domain: str,
        status: str,
        duration_ms: float,
    ) -> None:
        """Record a completed task event."""
        self._write(
            {
                "event": "task",
                "task_id": task_id,
                "domain": domain,
                "status": status,
                "duration_ms": duration_ms,
            }
        )

    def record_tool_call(
        self,
        tool_name: str,
        domain: str,
        status: str,
        duration_ms: float,
    ) -> None:
        """Record a single tool execution."""
        self._write(
            {
                "event": "tool_call",
                "tool_name": tool_name,
                "domain": domain,
                "status": status,
                "duration_ms": duration_ms,
            }
        )

    def record_llm_call(
        self,
        domain: str,
        tokens_used: int,
        duration_ms: float,
    ) -> None:
        """Record a single LLM API call."""
        self._write(
            {
                "event": "llm_call",
                "domain": domain,
                "tokens_used": tokens_used,
                "duration_ms": duration_ms,
            }
        )

    def record_review(
        self,
        domain: str,
        approved: bool,
        attempt_number: int,
    ) -> None:
        """Record a reviewer decision."""
        self._write(
            {
                "event": "review",
                "domain": domain,
                "approved": approved,
                "attempt_number": attempt_number,
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write(self, payload: dict[str, Any]) -> None:
        payload["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        line = json.dumps(payload, default=str)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        path = self._base_dir / f"{date_str}.jsonl"
        with self._write_lock:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
