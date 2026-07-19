"""Test-only task report writer."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def write_run_reports(task_id: str, status: str, results: dict[str, Any], trace_dir: Path) -> None:
    """Write JSON and Markdown reports for assertions or manual diagnostics."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "trinity-trace.jsonl"
    events: list[dict[str, Any]] = []
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = event.get("data", {})
            if isinstance(data, dict) and (data.get("task_id") == task_id or data.get("taskId") == task_id):
                events.append(event)
    report = {"task_id": task_id, "status": status, "timestamp": datetime.now().isoformat(), "results": results, "events": events}
    for name in (f"run_report_{task_id}.json", "run_report.json"):
        (trace_dir / name).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [f"# Trinity Pilot Task Report — {task_id}", "", f"- **Status:** {status}", "", "## Objectives Results"]
    for objective_id, result in results.items():
        lines.append(f"### `{objective_id}` — {result.get('status', 'unknown')}")
    for name in (f"run_report_{task_id}.md", "run_report.md"):
        (trace_dir / name).write_text("\n".join(lines), encoding="utf-8")
