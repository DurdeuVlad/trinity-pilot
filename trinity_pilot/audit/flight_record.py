from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

REQUIRED_KEYS = (
    "run_id",
    "task_id",
    "execution_path",
    "objectives",
    "signals",
    "attempts",
    "evidence",
    "reviewer",
    "recovery",
    "artifact_checks",
    "started_at",
    "ended_at",
    "final_status",
)
PRIMARY_JSON = "flight-record.json"
PRIMARY_MARKDOWN = "flight-summary.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_record(record: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in record]
    if missing:
        raise ValueError(f"Flight record missing required keys: {', '.join(missing)}")


def render_markdown_summary(record: dict[str, Any]) -> str:
    validate_record(record)
    attempts = record.get("attempts") or []
    reviewer = record.get("reviewer") or {}
    recovery = record.get("recovery") or {}
    checks = record.get("artifact_checks") or []
    lines = [
        f"# Flight Summary: {record['run_id']}",
        "",
        f"- Execution path: {record['execution_path']}",
        f"- Task: {record['task_id']}",
        f"- Final status: {record['final_status']}",
        f"- Started: {record['started_at']}",
        f"- Ended: {record['ended_at']}",
        "",
        "## Objectives",
    ]
    for objective in record.get("objectives") or []:
        lines.append(f"- {objective.get('objective_id', '<unknown>')}: {objective.get('goal', '')}")
    lines.extend(["", "## Attempts"])
    for attempt in attempts:
        lines.append(
            "- Attempt {attempt_number}: {status}; action={action}; evidence={evidence_keys}; error={error_summary}".format(
                attempt_number=attempt.get("attempt_number"),
                status=attempt.get("status"),
                action=attempt.get("action"),
                evidence_keys=",".join(attempt.get("evidence_keys", [])),
                error_summary=attempt.get("error_summary") or "",
            )
        )
    lines.extend(
        [
            "",
            "## Reviewer",
            f"- Verdict: {reviewer.get('verdict', 'unavailable')}",
            f"- Failure reason: {reviewer.get('failure_reason') or ''}",
            f"- Recovery hint: {reviewer.get('recovery_hint') or ''}",
            "",
            "## Recovery",
            f"- Intentional failure: {recovery.get('intentional_failure')}",
            f"- Second attempt changed: {recovery.get('second_attempt_changed')}",
            f"- Cause: {recovery.get('cause') or recovery.get('unavailable_reason') or ''}",
            f"- Reflection storage: {recovery.get('reflection_storage') or recovery.get('reflection_unavailable_reason') or ''}",
            "",
            "## Artifact Checks",
        ]
    )
    for check in checks:
        lines.append(f"- {check.get('name')}: passed={check.get('passed')} reason={check.get('reason', '')}")
    return "\n".join(lines) + "\n"


@dataclass
class FlightRecorder:
    output_root: Path
    run_id: str
    run_dir: Path

    @classmethod
    def start(cls, output_root: str | Path, *, prefix: str = "audit") -> "FlightRecorder":
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)
        for _ in range(20):
            run_id = f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
            run_dir = root / run_id
            try:
                run_dir.mkdir()
                return cls(root, run_id, run_dir)
            except FileExistsError:
                continue
        raise RuntimeError("Could not create unique audit run directory")

    def finalize(self, record: dict[str, Any]) -> tuple[Path, Path]:
        record = dict(record)
        record["run_id"] = self.run_id
        record.setdefault("ended_at", utc_now())
        validate_record(record)
        json_path = self.run_dir / PRIMARY_JSON
        md_path = self.run_dir / PRIMARY_MARKDOWN
        if json_path.exists() or md_path.exists():
            raise FileExistsError("Primary flight files already exist")
        if list(self.run_dir.glob("flight-record*.json")) or list(self.run_dir.glob("flight-summary*.md")):
            raise FileExistsError("Duplicate primary flight files would be ambiguous")
        self._atomic_write_json(json_path, record)
        self._atomic_write_text(md_path, render_markdown_summary(record))
        return json_path, md_path

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
            json.dump(data, tmp, indent=2, sort_keys=True)
            tmp.write("\n")
            temp_name = tmp.name
        os.replace(temp_name, path)

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
            tmp.write(text)
            temp_name = tmp.name
        os.replace(temp_name, path)
