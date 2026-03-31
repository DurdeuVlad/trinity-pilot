"""Runtime settings regressions for mock-mode orchestration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.orchestrator_core import OrchestratorCore


def test_orchestrator_core_forces_mock_key_when_gemini_mock_enabled(monkeypatch):
    monkeypatch.setenv("GEMINI_MOCK", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    core = OrchestratorCore()
    core.runtime_settings["gemini_api_key"] = "saved-live-key"

    try:
        assert core._resolve_api_key("gemini") == "mock"
    finally:
        core.deleteLater()
