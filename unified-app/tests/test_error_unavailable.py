"""Tests for backend-unavailable fast-fail message quality (UA-S3)."""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.error_handler import ErrorHandler


def test_map_backend_unavailable_reason_cli_domain() -> None:
    handler = ErrorHandler()
    result = handler.map_backend_unavailable_reason(
        "cli", "Domain 'cli' is not available (initialized adapters: none)"
    )
    assert result is not None
    assert "cli" in result
    assert "CLI" in result or "cli" in result
    assert "Settings" in result or "installed" in result.lower()


def test_map_backend_unavailable_reason_browser_domain() -> None:
    handler = ErrorHandler()
    result = handler.map_backend_unavailable_reason(
        "web", "Desktop backend is not available in this environment"
    )
    assert result is not None
    assert "web" in result
    assert "Playwright" in result or "Browser" in result


def test_map_backend_unavailable_reason_desktop_domain() -> None:
    handler = ErrorHandler()
    result = handler.map_backend_unavailable_reason(
        "desktop", "Trinity Core is not available in this environment"
    )
    assert result is not None
    assert "desktop" in result
    assert "Windows" in result or "UIA" in result or "enabled" in result.lower()


def test_map_backend_unavailable_reason_returns_none_for_unrelated_errors() -> None:
    handler = ErrorHandler()
    result = handler.map_backend_unavailable_reason(
        "cli", "KeyError: 'some_key' in nested dict"
    )
    assert result is None


def test_map_backend_unavailable_reason_no_raw_traceback_in_output() -> None:
    handler = ErrorHandler()
    error_with_traceback = (
        "Traceback (most recent call last):\n"
        "  File 'foo.py', line 12\n"
        "RuntimeError: Domain 'cli' is not available"
    )
    result = handler.map_backend_unavailable_reason("cli", error_with_traceback)
    assert result is not None
    assert "File" not in result
    assert "Traceback" not in result
    assert "line 12" not in result


def test_build_user_message_health_check_failed_category() -> None:
    handler = ErrorHandler()
    result = handler.build_user_message("health check failed", category="health_check_failed")
    assert "health check" in result.lower()
    assert "Traceback" not in result


def test_map_backend_unavailable_unknown_domain_includes_generic_hint() -> None:
    handler = ErrorHandler()
    result = handler.map_backend_unavailable_reason(
        "ftp", "Domain 'ftp' is not available"
    )
    assert result is not None
    assert "ftp" in result
    assert "Settings" in result or "enabled" in result.lower()
