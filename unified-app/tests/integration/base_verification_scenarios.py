"""
Base class for deterministic verification scenarios.

build_verification() is a pure function: given the same task, execution log,
and backend result, it always returns the same VerificationEnvelope. Tests in
this family verify that the deterministic postcondition rules fire correctly.

No mocks, no LLM, no network. Avoid check kinds that do I/O:
  - DO NOT use: file_exists, process_running
  - Safe kinds: url_equals, url_contains, text_contains, text_absent,
                element_exists, command_exit_code, visible_tool_execution
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from .base_orchestrator_scenarios import ContractMixin

# Ensure trinity_core is on path (conftest adds repo root; trinity_core lives there)
_TRINITY_CORE_ROOT = Path(__file__).resolve().parents[4] / "trinity-pilot"
if str(_TRINITY_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRINITY_CORE_ROOT))

from trinity_core.models import TaskInput, VerificationEnvelope
from trinity_core.verification import build_verification


# ---------------------------------------------------------------------------
# Base scenario — no "Test" prefix so pytest does not collect it directly
# ---------------------------------------------------------------------------

class BaseVerificationScenario(ContractMixin):
    """
    Contract: every concrete subclass declares the inputs and the expected
    VerificationEnvelope outcome. The 9 test methods run automatically
    against every subclass.

    To add a new scenario: subclass and override the class variables.
    The fixture is sync because build_verification() is synchronous.
    """

    # --- inputs (subclasses override) ------------------------------------
    module: str = "cli"
    task_description: str = "run a health check"
    task_verification_checks: list[dict[str, Any]] = []
    execution_log: list[dict[str, Any]] = []
    backend_result: dict[str, Any] = {}
    output_text: str = ""
    task_status: str = "success"

    # --- expected outputs (subclasses override) --------------------------
    expected_status: str = "unknown"           # "success"|"failure"|"unknown"|"not_requested"
    expected_summary_contains: str = ""        # optional substring; "" = skip check

    # --- contract bounds (subclasses may override) -----------------------
    required_evidence_keys: tuple[str, ...] = ()  # empty = skip check

    # --- internal constants ----------------------------------------------
    _VALID_CHECK_STATUSES: frozenset[str] = frozenset({"success", "failure", "unknown"})
    _VALID_SOURCES: frozenset[str] = frozenset({"executor", "fallback", "mixed", "none"})

    # --- runtime state (populated by fixture) ----------------------------
    _result: VerificationEnvelope

    # --- fixture ----------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _run_verification(self) -> None:
        """
        Call build_verification() once and store the result on self so each
        test method can assert a single property independently.
        """
        task = TaskInput(
            task_id="det-scenario-001",
            description=self.task_description,
            domain=self.module,
            verification_checks=list(self.task_verification_checks),
        )
        self._result = build_verification(
            task=task,
            module=self.module,
            backend_result=dict(self.backend_result),
            task_status=self.task_status,
            execution_log=list(self.execution_log),
            output_text=self.output_text,
        )

    # --- exact-value assertions (inherited by every concrete subclass) ---

    def test_status_matches_expected(self) -> None:
        assert self._result.status == self.expected_status, (
            f"Expected status={self.expected_status!r}, got {self._result.status!r}. "
            f"Summary: {self._result.summary!r}"
        )

    def test_summary_is_present(self) -> None:
        assert self._result.summary, "VerificationEnvelope.summary must be a non-empty string"

    def test_summary_contains_keyword(self) -> None:
        if not self.expected_summary_contains:
            pytest.skip("No expected_summary_contains declared for this scenario")
        assert self.expected_summary_contains.lower() in (self._result.summary or "").lower(), (
            f"Expected {self.expected_summary_contains!r} in summary, got: {self._result.summary!r}"
        )

    def test_envelope_has_checks_field(self) -> None:
        assert self._result.checks is not None, "VerificationEnvelope.checks must not be None"

    def test_status_is_valid_value(self) -> None:
        valid = {"success", "failure", "unknown", "not_requested"}
        assert self._result.status in valid, (
            f"status={self._result.status!r} is not a valid VerificationEnvelope status"
        )

    # --- contract assertions (envelope internal consistency) -------------

    def test_check_structure_integrity(self) -> None:
        """Every check in the envelope must have a non-empty kind and a valid status."""
        if not self._result.checks:
            pytest.skip("No checks in this scenario — structure integrity N/A")
        errors: list[str] = []
        for i, check in enumerate(self._result.checks):
            if not (check.kind or "").strip():
                errors.append(f"checks[{i}].kind is empty or None")
            if check.status not in self._VALID_CHECK_STATUSES:
                errors.append(
                    f"checks[{i}] kind={check.kind!r}: "
                    f"status={check.status!r} not in {sorted(self._VALID_CHECK_STATUSES)}"
                )
        if errors:
            pytest.fail("Check structure violations:\n" + "\n".join(errors))

    def test_review_required_consistency(self) -> None:
        """status='unknown' must imply review_required=True."""
        if self._result.status == "unknown" and not self._result.review_required:
            pytest.fail(
                "status='unknown' but review_required=False. "
                "build_verification() sets review_required=(status=='unknown')."
            )

    def test_source_field_validity(self) -> None:
        """envelope.source must be one of the four values from models.py Literal."""
        if self._result.source not in self._VALID_SOURCES:
            pytest.fail(
                f"source={self._result.source!r} not in {sorted(self._VALID_SOURCES)}"
            )

    def test_required_evidence_keys(self) -> None:
        """If required_evidence_keys is declared, all keys must be present in evidence."""
        if not self.required_evidence_keys:
            pytest.skip("No required_evidence_keys declared for this scenario")
        missing = [k for k in self.required_evidence_keys if k not in self._result.evidence]
        if missing:
            pytest.fail(
                f"VerificationEnvelope.evidence missing declared keys: {missing}. "
                f"Present keys: {sorted(self._result.evidence.keys())}"
            )
