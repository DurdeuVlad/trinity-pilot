from __future__ import annotations

from orchestrator.failure_classifier import FailureKind, classify


def test_classify_transient_timeout() -> None:
    assert classify("Request timeout while waiting for backend") == FailureKind.TRANSIENT


def test_classify_transient_rate_limit() -> None:
    assert classify("API error: 429 rate limit reached") == FailureKind.TRANSIENT


def test_classify_permanent_not_found() -> None:
    assert classify("Target file was not found") == FailureKind.PERMANENT


def test_classify_permanent_unavailable() -> None:
    assert classify("Desktop backend unavailable in this environment") == FailureKind.PERMANENT


def test_classify_ambiguous_generic_failure() -> None:
    assert classify("Action failed unexpectedly") == FailureKind.AMBIGUOUS


def test_classify_ambiguous_empty_text() -> None:
    assert classify("") == FailureKind.AMBIGUOUS


def test_classify_transient_connection_refused() -> None:
    assert classify("connection refused to remote endpoint") == FailureKind.TRANSIENT


def test_classify_transient_503_response() -> None:
    assert classify("received 503 from backend service") == FailureKind.TRANSIENT


def test_classify_permanent_not_installed() -> None:
    assert classify("application is not installed on this system") == FailureKind.PERMANENT


def test_classify_permanent_infeasible() -> None:
    assert classify("infeasible: target element is outside viewport") == FailureKind.PERMANENT


def test_classify_permanent_cannot_open() -> None:
    assert classify("cannot open the requested document") == FailureKind.PERMANENT


def test_classify_transient_wins_over_permanent_on_mixed() -> None:
    # TRANSIENT check runs first; mixed text resolves to TRANSIENT
    assert classify("timeout waiting for element that does not exist") == FailureKind.TRANSIENT


def test_classify_ambiguous_none_input() -> None:
    assert classify(None) == FailureKind.AMBIGUOUS  # type: ignore[arg-type]


def test_classify_transient_window_not_found_during_attach() -> None:
    assert classify("window_not_found while attaching to the launched app") == FailureKind.TRANSIENT


def test_classify_transient_selector_not_found_after_navigation() -> None:
    assert classify("selector not found after page navigation") == FailureKind.TRANSIENT
