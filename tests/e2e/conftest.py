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

try:
    _STARTUP_MARKER = Path.home() / ".ai" / "tp_gui_startup.marker"
    _STARTUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
    with _STARTUP_MARKER.open("a", encoding="utf-8") as _marker:
        _marker.write("conftest-before-settings\n")
except OSError:
    pass

from trinity_pilot.config import Settings

try:
    with _STARTUP_MARKER.open("a", encoding="utf-8") as _marker:
        _marker.write("conftest-after-settings\n")
except OSError:
    pass

# pywinauto reads this module-level setting on its first import. Keep it ahead
# of every GUI fixture so the interactive Scheduled Task process uses MTA.
if sys.platform == "win32":
    sys.coinit_flags = 0  # COINIT_MULTITHREADED


# ---------------------------------------------------------------------------
# QApplication â€” session-scoped, guarded against double-init
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Create (or reuse) a QApplication instance for the entire test session."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Do NOT call app.exec() or app.quit() here â€” we just need the instance


# ---------------------------------------------------------------------------
# Settings â€” session-scoped; skip whole session if no API key
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def e2e_settings() -> Settings:
    """Load Settings from environment. Skip session if GEMINI_API_KEY is absent."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set â€” skipping e2e tests")
    return Settings.from_env()


# ---------------------------------------------------------------------------
# tmp_db_path â€” function-scoped isolated DB path
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> str:
    """Return a unique SQLite DB path inside the test's tmp_path."""
    db_file = tmp_path / f"test_{uuid.uuid4().hex[:8]}.db"
    return str(db_file)


# ---------------------------------------------------------------------------
# cleanup_registry â€” function-scoped path accumulator with finalizer
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
# bridge_harness â€” function-scoped BridgeTestHarness
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
# Marker: desktop_available â€” skip if not on Windows with a visible desktop
# ---------------------------------------------------------------------------

@pytest.fixture()
def desktop_available():
    """Skip if not on a visible Windows desktop."""
    if sys.platform != "win32":
        pytest.skip("Desktop tests require Windows")
    yield


# ---------------------------------------------------------------------------
# app â€” function-scoped GUI driver (Layer 3: full Qt GUI via pywinauto)
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(request):
    """Fresh Trinity Pilot GUI instance per test. Process is killed on teardown.

    Skipped automatically on non-Windows or if GEMINI_API_KEY is absent.
    Each test gets an isolated app instance with a clean DB state.
    """
    if sys.platform != "win32":
        pytest.skip("GUI tests require Windows")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set â€” skipping GUI e2e tests")

    from tests.e2e._gui_driver import AppDriver

    driver = AppDriver.launch()
    yield driver

    safe_name = request.node.name.replace("/", "_").replace("\\", "_")[:60]
    driver.snap(f"teardown_{safe_name}")
    checkpoints = getattr(driver, "infra_checkpoints", {})
    driver.close()
    try:
        import json
        temp_file = Path(__file__).resolve().parent.parent.parent / "temp_infra.json"
        temp_file.write_text(json.dumps(checkpoints), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Marker registration (also in pyproject.toml)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests requiring live orchestrator")
    config.addinivalue_line("markers", "desktop: requires visible Windows desktop")
    config.addinivalue_line("markers", "slow: long-running scenarios")
    config.addinivalue_line("markers", "external_network: uses a public website; not part of deterministic acceptance")
