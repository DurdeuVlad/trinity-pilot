"""Unified NDJSON trace emitter for Trinity Pilot.

Environment:
  TRINITY_TRACE=1|0     — force enable/disable (default: auto)
  TRINITY_TRACE_DIR     — output directory (default: <repo>/.trace)

Auto-enabled when TRINITY_CONNECT_EXISTING=1 or DB_PATH ends with _trinity_test.db
(E2E / test-mode launches).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

_TRACE_FILENAME = "trinity-trace.jsonl"
_DEFAULT_DIR = Path(__file__).resolve().parents[2] / ".trace"


def is_enabled() -> bool:
    """Return True when trace emission is active."""
    env = os.environ.get("TRINITY_TRACE", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    if os.environ.get("TRINITY_CONNECT_EXISTING") == "1":
        return True
    db_path = os.environ.get("DB_PATH", "")
    if db_path.endswith("_trinity_test.db"):
        return True
    return False


def _trace_dir() -> Path:
    d = os.environ.get("TRINITY_TRACE_DIR", "").strip()
    if d:
        return Path(d)
    return _DEFAULT_DIR


def _trace_path() -> Path:
    return _trace_dir() / _TRACE_FILENAME


def _json_default(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)


def emit(
    location: str,
    message: str,
    data: dict | None = None,
    *,
    hypothesis_id: str = "",
    run_id: str = "probe",
    span: str = "",
) -> None:
    """Append one NDJSON trace event. No-op when tracing is disabled."""
    if not is_enabled():
        return

    ts = int(time.time() * 1000)
    entry: dict[str, Any] = {
        "ts": ts,
        "timestamp": ts,
        "location": location,
        "message": message,
        "data": data or {},
        "hypothesisId": hypothesis_id,
        "runId": run_id,
    }
    if span:
        entry["span"] = span

    line = json.dumps(entry, ensure_ascii=False, default=_json_default) + "\n"
    _write_line(line)


def emit_signal(signal: Any) -> None:
    """Record an orchestrator signal as a trace span."""
    sig_type = type(signal).__name__
    data: dict[str, Any] = {}
    if is_dataclass(signal):
        data = asdict(signal)
    else:
        data = {"repr": repr(signal)}
    emit(
        "orchestrator.signal",
        sig_type,
        data,
        span="signal",
    )


def export_attempts_json(task_id: str, attempts: list[Any]) -> Path | None:
    """Write attempt logs for a task to attempts-<task_id>.json in the trace dir."""
    if not is_enabled():
        return None

    out_dir = _trace_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"attempts-{task_id}.json"

    payload: list[dict[str, Any]] = []
    for att in attempts:
        if is_dataclass(att):
            row = asdict(att)
            fr = row.get("failure_reason")
            if fr is not None and not isinstance(fr, str):
                row["failure_reason"] = str(fr)
            payload.append(row)
        elif isinstance(att, dict):
            payload.append(att)
        else:
            payload.append({"repr": repr(att)})

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"task_id": task_id, "attempts": payload}, f, indent=2, ensure_ascii=False)
        emit(
            "trace.py:export_attempts_json",
            "attempts_exported",
            {"task_id": task_id, "count": len(payload), "path": str(out_path)},
            span="evidence",
        )
        return out_path
    except Exception as exc:
        print(f"[trace] attempts export failed: {exc}", file=sys.stderr)
        return None


def _write_line(line: str) -> None:
    """Write to primary trace file, legacy log, with stderr fallback."""
    written = False
    try:
        path = _trace_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        written = True
    except Exception as exc:
        print(f"[trace] write failed ({exc}): {line[:200]}", file=sys.stderr)

    if not written:
        print(f"[trace] {line.rstrip()}", file=sys.stderr)
