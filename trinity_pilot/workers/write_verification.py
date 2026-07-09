from __future__ import annotations

from pathlib import Path
from typing import Any


def verify_and_write_file(path: str, content: str, evidence: dict[str, Any]) -> str:
    """Write content to path, then verify the file actually exists on disk.

    Records `write_file_failures` / `written_files_verified` in evidence so
    ObjectiveReviewer's programmatic floor (C1) catches a silent write failure
    or missing artifact regardless of what the action_log narrates. Every
    worker that exposes a write_file tool must route through this instead of
    writing directly, otherwise the LLM reviewer is the only check.
    """
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        evidence.setdefault("write_file_failures", []).append({"path": path, "error": error})
        evidence.setdefault("action_log", []).append(f"write_file FAILED: {path}: {exc}")
        return f"write_file failed: {path}: {exc}"

    exists_after = p.exists()
    evidence.setdefault("written_files_verified", {})[path] = exists_after
    if not exists_after:
        evidence.setdefault("write_file_failures", []).append(
            {"path": path, "error": "file missing immediately after write"}
        )
    evidence.setdefault("action_log", []).append(
        f"write_file: {path} ({len(content)} chars) verified_exists={exists_after}"
    )
    return f"File written: {path} ({len(content)} chars) verified_exists={exists_after}"
