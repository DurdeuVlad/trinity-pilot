"""
Concrete deterministic verification scenarios.

Each class sets class-variable overrides only; all 5 test methods are
inherited from BaseVerificationScenario and run automatically by pytest.

Total: 8 scenarios × 9 assertions = 72 test cases.
"""
from __future__ import annotations

import pytest

from .base_verification_scenarios import BaseVerificationScenario

pytestmark = pytest.mark.integration


class TestCliUnknownWhenNoEvidence(BaseVerificationScenario):
    """
    CLI task with no execution log and no explicit checks.
    No exit codes, no evidence → deterministic rules cannot decide → 'unknown'.
    """
    module = "cli"
    task_description = "run a health check"
    task_verification_checks = []
    execution_log = []
    backend_result = {}
    output_text = ""
    task_status = "success"
    expected_status = "unknown"
    expected_summary_contains = "incomplete"


class TestCliSuccessWithZeroExitCode(BaseVerificationScenario):
    """
    CLI task where the command returned exit code 0.
    Fallback rule: all exit codes == 0 → 'success'.
    """
    module = "cli"
    task_description = "list running processes"
    task_verification_checks = []
    execution_log = [
        {
            "turn": 1,
            "action": "run_command",
            "result": "success",
            "details": "PID  NAME\n1234 python",
            "exit_code": 0,
            "timestamp": "2026-01-01T00:00:00",
            "metadata": {},
        }
    ]
    backend_result = {}
    output_text = "PID  NAME\n1234 python"
    task_status = "success"
    expected_status = "success"
    expected_summary_contains = "command_exit_code"


class TestCliFailureNonZeroExitCode(BaseVerificationScenario):
    """
    CLI task where the backend reports task_status='failure' and the error
    is not transient. Deterministic rule: non-transient failure → 'failure'.
    """
    module = "cli"
    task_description = "run a command"
    task_verification_checks = []
    execution_log = [
        {
            "turn": 1,
            "action": "run_command",
            "result": "failure",
            "details": "Access is denied.",
            "exit_code": 1,
            "timestamp": "2026-01-01T00:00:00",
            "metadata": {},
        }
    ]
    backend_result = {"error": "command failed with exit code 1"}
    output_text = ""
    task_status = "failure"
    expected_status = "failure"
    expected_summary_contains = "command_exit_code"


class TestBrowserSuccessExplicitUrlMatch(BaseVerificationScenario):
    """
    Browser task with an explicit url_equals check that passes.
    Explicit checks take priority over fallback heuristics.
    """
    module = "browser"
    task_description = "navigate to example.com"
    task_verification_checks = [
        {"kind": "url_equals", "target": "current_url", "expected": "https://example.com"}
    ]
    execution_log = []
    backend_result = {"current_url": "https://example.com"}
    output_text = ""
    task_status = "success"
    expected_status = "success"
    expected_summary_contains = "url_equals"


class TestBrowserFailureExplicitUrlMismatch(BaseVerificationScenario):
    """
    Browser task with an explicit url_equals check that fails because
    the actual URL does not match the expected URL.
    """
    module = "browser"
    task_description = "navigate to example.com"
    task_verification_checks = [
        {"kind": "url_equals", "target": "current_url", "expected": "https://example.com"}
    ]
    execution_log = []
    backend_result = {"current_url": "https://wrong-site.com"}
    output_text = ""
    task_status = "success"
    expected_status = "failure"
    expected_summary_contains = "url_equals"


class TestTextContainsFound(BaseVerificationScenario):
    """
    Explicit text_contains check succeeds because the expected text
    appears in backend_result['extracted_text'] → combined_text.
    """
    module = "cli"
    task_description = "run a command and show output"
    task_verification_checks = [
        {"kind": "text_contains", "target": "combined_text", "expected": "Hello World"}
    ]
    execution_log = []
    backend_result = {"extracted_text": "The script printed: Hello World successfully."}
    output_text = ""
    task_status = "success"
    expected_status = "success"
    expected_summary_contains = "text_contains"


class TestTextContainsNotFound(BaseVerificationScenario):
    """
    Explicit text_contains check fails because the expected text does not
    appear in the execution output.
    """
    module = "cli"
    task_description = "run a command and show output"
    task_verification_checks = [
        {"kind": "text_contains", "target": "combined_text", "expected": "Hello World"}
    ]
    execution_log = []
    backend_result = {"extracted_text": "The script printed: Goodbye Universe."}
    output_text = ""
    task_status = "success"
    expected_status = "failure"
    expected_summary_contains = "text_contains"


class TestTransientFailureMarkedUnknown(BaseVerificationScenario):
    """
    Backend reports task_status='failure' but the error message contains a
    transient marker ('element not visible'). Deterministic rule: transient
    failure → 'unknown' (needs retry, not a definitive failure).
    """
    module = "browser"
    task_description = "click the submit button"
    task_verification_checks = []
    execution_log = []
    # error drives _decide_status (→ unknown); extracted_text drives _build_summary (→ "settling")
    backend_result = {
        "error": "element not visible: submit button",
        "extracted_text": "element not visible",
    }
    output_text = ""
    task_status = "failure"
    expected_status = "unknown"
    expected_summary_contains = "settling"
