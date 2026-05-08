"""Evidence schema validation tests — required keys enforced per domain."""
import pytest

from trinity_pilot.core.types import DomainType
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence


def _browser_evidence() -> dict:
    return {
        "domain": "browser", "objective_id": "obj-1",
        "screenshot": None, "dom_snapshot": None,
        "page_title": None, "page_url": None,
        "trace_path": None, "error": None,
    }


def _terminal_evidence() -> dict:
    return {
        "domain": "terminal", "objective_id": "obj-1",
        "stdout": "", "stderr": "", "exit_code": 0,
        "created_files": [], "workspace": "/tmp/x", "error": None,
    }


def _desktop_evidence() -> dict:
    return {
        "domain": "desktop", "objective_id": "obj-1",
        "screenshot": None, "element_tree_snapshot": None,
        "action_log": [], "degraded_mode": False, "error": None,
    }


class TestValidateEvidence:
    def test_valid_browser_evidence_passes(self):
        validate_evidence(DomainType.BROWSER, _browser_evidence())

    def test_valid_terminal_evidence_passes(self):
        validate_evidence(DomainType.TERMINAL, _terminal_evidence())

    def test_valid_desktop_evidence_passes(self):
        validate_evidence(DomainType.DESKTOP, _desktop_evidence())

    def test_browser_missing_key_raises(self):
        ev = _browser_evidence()
        del ev["screenshot"]
        with pytest.raises(WorkerError, match="screenshot"):
            validate_evidence(DomainType.BROWSER, ev)

    def test_terminal_missing_key_raises(self):
        ev = _terminal_evidence()
        del ev["stdout"]
        with pytest.raises(WorkerError, match="stdout"):
            validate_evidence(DomainType.TERMINAL, ev)

    def test_desktop_missing_key_raises(self):
        ev = _desktop_evidence()
        del ev["action_log"]
        with pytest.raises(WorkerError, match="action_log"):
            validate_evidence(DomainType.DESKTOP, ev)
