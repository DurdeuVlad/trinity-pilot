#!/usr/bin/env python3
"""Human-readable reader for trinity-trace.jsonl NDJSON timeline files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _format_event(entry: dict) -> str:
    ts = entry.get("ts", entry.get("timestamp", 0))
    loc = entry.get("location", "?")
    msg = entry.get("message", "")
    span = entry.get("span", "")
    data = entry.get("data") or {}
    prefix = f"[{span}] " if span else ""
    data_s = ""
    if data:
        try:
            data_s = "  " + json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            data_s = f"  {data!r}"
    return f"{ts:>13}  {prefix}{loc}: {msg}{data_s}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print a human-readable timeline from trinity-trace.jsonl",
    )
    parser.add_argument(
        "trace_file",
        type=Path,
        help="Path to trinity-trace.jsonl",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=0,
        help="Show only the last N events (0 = all)",
    )
    parser.add_argument(
        "--span",
        default="",
        help="Filter to events with this span value (e.g. orchestrator, bridge, signal)",
    )
    args = parser.parse_args()

    if not args.trace_file.exists():
        print(f"File not found: {args.trace_file}", file=sys.stderr)
        return 1

    raw = args.trace_file.read_text(encoding="utf-8").strip()
    if not raw:
        print("(empty trace file)")
        return 0

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if args.tail:
        lines = lines[-args.tail :]

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            print(f"(invalid JSON) {line[:120]}")
            continue
        if args.span and entry.get("span") != args.span:
            continue
        print(_format_event(entry))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
