"""Pytest configuration for trinity_core."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Explicitly load .env so GEMINI_API_KEY (and other vars) are available
# regardless of whether coverage is active or which modules happen to
# import python-dotenv as a side effect.
try:
    from dotenv import load_dotenv
    _repo_root = Path(__file__).parent.parent
    _candidate = _repo_root / "unified-app" / ".env"
    if _candidate.exists():
        load_dotenv(_candidate, override=False)
except ImportError:
    pass


collect_ignore_glob = ["demo_real_test.py"]

LIVE_TEST_ENV_VAR = "TRINITY_RUN_LIVE"
LIVE_TEST_MARKERS = ("integration", "performance")


def live_suite_enabled() -> bool:
    """Return True when live Trinity test suites were explicitly requested."""
    return os.getenv(LIVE_TEST_ENV_VAR) == "1"


def pytest_configure(config: pytest.Config) -> None:
    """Register the live-suite opt-in marker description for local help output."""
    config.addinivalue_line(
        "markers",
        f"live_suite: requires {LIVE_TEST_ENV_VAR}=1 to run against live adapters",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip live integration/performance tests unless explicitly enabled."""
    if live_suite_enabled():
        return

    skip_live = pytest.mark.skip(
        reason=(
            f"live Trinity test disabled by default; set {LIVE_TEST_ENV_VAR}=1 to run"
        )
    )

    for item in items:
        if any(item.get_closest_marker(marker) for marker in LIVE_TEST_MARKERS):
            item.add_marker(skip_live)
            item.add_marker("live_suite")
