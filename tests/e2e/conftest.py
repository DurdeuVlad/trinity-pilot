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

def _snapshot_pids() -> set[int]:
    """Return the set of all currently running PIDs."""
    import psutil
    return {p.pid for p in psutil.process_iter(["pid"])}


def _kill_new_procs(before: set[int]) -> None:
    """Kill every process whose PID wasn't present in *before*.

    This catches any application the desktop worker launched during the test,
    regardless of its name.  Uses psutil.kill() with a taskkill /F fallback
    for UWP app-container processes that psutil cannot terminate directly.
    """
    import subprocess as _sp
    import psutil

    for proc in psutil.process_iter(["pid", "name"]):
        if proc.pid in before:
            continue
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # UWP / protected processes need taskkill
            name = proc.info.get("name") or ""
            if name:
                _sp.run(
                    ["taskkill", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                )
        except Exception:
            pass


@pytest.fixture()
def desktop_available():
    """Skip if not on a visible Windows desktop.

    Snapshots all running PIDs before the test; after the test kills every
    process that wasn't there at the start.  This automatically cleans up
    any application the desktop worker launched, regardless of its name.
    """
    if sys.platform != "win32":
        pytest.skip("Desktop tests require Windows")
    pids_before = _snapshot_pids()
    yield
    # Teardown: kill anything the worker spawned
    _kill_new_procs(pids_before)


# ---------------------------------------------------------------------------
# Marker registration (also in pyproject.toml)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests requiring live orchestrator")
    config.addinivalue_line("markers", "desktop: requires visible Windows desktop")
    config.addinivalue_line("markers", "slow: long-running scenarios")
