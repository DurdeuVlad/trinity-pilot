"""Evidence schema validation — enforces required keys per domain at worker boundary."""
from __future__ import annotations

from trinity_pilot.core.types import DomainType
from trinity_pilot.workers.base import WorkerError

_REQUIRED_KEYS: dict[DomainType, list[str]] = {
    DomainType.BROWSER: [
        "domain", "objective_id", "screenshot", "dom_snapshot",
        "page_title", "page_url", "trace_path", "error",
    ],
    DomainType.TERMINAL: [
        "domain", "objective_id", "stdout", "stderr",
        "exit_code", "created_files", "workspace", "error",
    ],
    DomainType.DESKTOP: [
        "domain", "objective_id", "screenshot", "element_tree_snapshot",
        "action_log", "degraded_mode", "error",
    ],
}


def validate_evidence(domain: DomainType, evidence: dict) -> None:
    """Raise WorkerError if evidence dict is missing required keys for domain."""
    required = _REQUIRED_KEYS.get(domain)
    if required is None:
        return  # MIXED or unknown domain — no schema
    missing = [k for k in required if k not in evidence]
    if missing:
        raise WorkerError(
            f"Evidence for domain '{domain.value}' missing required keys: {missing}"
        )
