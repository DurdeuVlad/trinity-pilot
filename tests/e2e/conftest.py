"""Shared fixtures for e2e tests."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Generator

import pytest

from trinity_pilot.config import Settings


# ---------------------------------------------------------------------------
# QApplication — session-scoped, guarded against double-init
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Create (or reuse) a QApplication instance for the entire test session."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Do NOT call app.exec() or app.quit() here — we just need the instance


# ---------------------------------------------------------------------------
# Settings — session-scoped; skip whole session if no API key
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def e2e_settings() -> Settings:
    """Load Settings from environment. Skip session if GEMINI_API_KEY is absent."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set — skipping e2e tests")
    return Settings.from_env()


# ---------------------------------------------------------------------------
# tmp_db_path — function-scoped isolated DB path
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> str:
    """Return a unique SQLite DB path inside the test's tmp_path."""
    db_file = tmp_path / f"test_{uuid.uuid4().hex[:8]}.db"
    return str(db_file)


# ---------------------------------------------------------------------------
# cleanup_registry — function-scoped path accumulator with finalizer
# ---------------------------------------------------------------------------

@pytest.fixture()
def cleanup_registry(tmp_path: Path) -> Generator[list[Path], None, None]:
    """Yield a list; append paths to it. Finalizer removes them regardless of pass/fail."""
    paths: list[Path] = []
    manifest = tmp_path / "cleanup_manifest.json"
    manifest.write_text(json.dumps([]), encoding="utf-8")

    yield paths

    # Write final manifest for the atexit safety net
    manifest.write_text(
        json.dumps([str(p) for p in paths], indent=2), encoding="utf-8"
    )

    # Clean up
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# bridge_harness — function-scoped BridgeTestHarness
# ---------------------------------------------------------------------------

@pytest.fixture()
def bridge_harness(qapp, e2e_settings: Settings, tmp_db_path: str):
    """Yield a ready-to-use BridgeTestHarness, disposed after the test."""
    from tests.e2e._scenario import BridgeTestHarness

    signals_q: asyncio.Queue = asyncio.Queue()
    harness = BridgeTestHarness(e2e_settings, tmp_db_path, signals_queue=signals_q)
    yield harness
    harness.dispose()


# ---------------------------------------------------------------------------
# Marker: desktop_available — skip if not on Windows with a visible desktop
# ---------------------------------------------------------------------------

# Processes the desktop worker is allowed to launch during tests.
# These are killed in teardown so they don't leak between tests.
_DESKTOP_TEST_PROCS = {
    "notepad.exe",
    "calc.exe",
    "calculatorapp.exe",   # Win10/11 modern Calculator (lowercase for case-insensitive match)
    "mspaint.exe",
    "wordpad.exe",
    "write.exe",
}


def _kill_desktop_test_procs() -> None:
    """Kill any known desktop-test processes still running.

    Uses psutil first; falls back to `taskkill /F /IM <name>` for UWP apps
    (e.g. CalculatorApp.exe) that psutil cannot terminate due to app-container
    sandboxing.
    """
    import subprocess as _sp
    import psutil

    killed: set[str] = set()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name in _DESKTOP_TEST_PROCS:
                try:
                    proc.kill()
                    killed.add(proc.info["name"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Fallback: taskkill handles UWP sandbox processes
                    _sp.run(
                        ["taskkill", "/F", "/IM", proc.info["name"]],
                        capture_output=True,
                    )
                    killed.add(proc.info["name"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


@pytest.fixture()
def desktop_available():
    """Skip if not on a visible Windows desktop. Kill test apps on teardown."""
    if sys.platform != "win32":
        pytest.skip("Desktop tests require Windows")
    yield
    # Teardown: kill any apps the worker opened during the test
    _kill_desktop_test_procs()


# ---------------------------------------------------------------------------
# Marker registration (also in pyproject.toml)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests requiring live orchestrator")
    config.addinivalue_line("markers", "desktop: requires visible Windows desktop")
    config.addinivalue_line("markers", "slow: long-running scenarios")
