from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Add subrepo paths for cli_backend, desktop_io_models, browser_agent, and audit_debugger
CLI_AUTOMATION_POC = REPO_ROOT / "cli-automation-poc"
API_ACCESSIBILITY_POC = REPO_ROOT / "api-accessibility-poc"
BROWSER_GUI_AUTOMATION = REPO_ROOT / "browser-gui-automation"
AUDIT_DEBUGGER = REPO_ROOT / "audit-debugger" / "src"
if str(CLI_AUTOMATION_POC) not in sys.path:
    sys.path.insert(0, str(CLI_AUTOMATION_POC))
if str(API_ACCESSIBILITY_POC) not in sys.path:
    sys.path.insert(0, str(API_ACCESSIBILITY_POC))
if str(BROWSER_GUI_AUTOMATION) not in sys.path:
    sys.path.insert(0, str(BROWSER_GUI_AUTOMATION))
if str(AUDIT_DEBUGGER) not in sys.path:
    sys.path.insert(0, str(AUDIT_DEBUGGER))

from testing.gemini_mock.activator import activate, deactivate
from testing.gemini_mock.backends.queue_backend import QueueBackend


pytest_plugins = ["testing.gemini_mock.pytest_plugin"]


if os.getenv("LIVE_GEMINI_SMOKE", "0") != "1":
    os.environ.setdefault("GEMINI_API_KEY", "mock")


_LIVE_SMOKE_NODE_FRAGMENTS = (
    "tests/integration/test_live_cli_smoke.py".replace("/", os.sep),
    "tests/integration/test_live_browser_smoke.py".replace("/", os.sep),
    "tests/integration/test_live_desktop_smoke.py".replace("/", os.sep),
    "tests/integration/test_live_cross_domain_smoke.py".replace("/", os.sep),
)
_RELOAD_MODULES = (
    "orchestrator.trinity_bridge",
    "orchestrator.orchestrator_core",
    "trinity_core.adapters.cli",
    "trinity_core.adapters.browser",
    "trinity_core.adapters.desktop",
    "trinity_core.trinity",
    "cli_planner",
    "cli_backend",
    "browser_agent.core.planner",
    "browser_agent.core.verifier",
    "browser_agent.core.agent",
    "browser_agent.main",
    "generic_planner",
    "generic_backend",
)


def _purge_google_generativeai_modules() -> None:
    for module_name in tuple(sys.modules):
        if module_name == "google" or module_name.startswith("google."):
            sys.modules.pop(module_name, None)


def _reload_loaded_modules() -> None:
    for module_name in _RELOAD_MODULES:
        module = sys.modules.get(module_name)
        if module is not None:
            importlib.reload(module)


@pytest.fixture(scope="module", autouse=True)
def configure_live_gemini_module_state(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Let the dedicated live smoke module run against the real Gemini SDK."""

    module_path = str(getattr(request.module, "__file__", "")).replace("/", os.sep)
    live_enabled = os.getenv("LIVE_GEMINI_SMOKE", "0") == "1"
    should_unmock = any(fragment in module_path for fragment in _LIVE_SMOKE_NODE_FRAGMENTS) and live_enabled
    if not should_unmock:
        yield
        return

    deactivate()
    _purge_google_generativeai_modules()
    _reload_loaded_modules()
    try:
        yield
    finally:
        activate(backend=QueueBackend())
        _reload_loaded_modules()
