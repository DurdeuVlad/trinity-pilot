"""Regression tests for startup preflight launch from the app entrypoint."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import main as app_main


def test_main_starts_async_preflight_when_api_key_is_available(monkeypatch):
    """main() should launch the deferred live preflight when a key exists."""
    startup_config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="live-key",
        key_source="environment",
        env_path=None,
    )
    startup_readiness = app_main.StartupReadiness(
        provider_name="gemini",
        ready=False,
        user_message="Checking Gemini connection...",
        block_task_submission=True,
    )
    seen: dict[str, object] = {}

    class FakeApplication:
        def __init__(self, argv):
            seen["argv"] = argv

        def exec(self) -> int:
            return 0

    class FakeWindow:
        def __init__(self, startup_readiness=None) -> None:
            seen["window_readiness"] = startup_readiness
            seen["window"] = self

        def showMaximized(self) -> None:
            seen["show_maximized"] = True

        def start_async_preflight(self, config) -> None:
            seen["preflight_config"] = config

    monkeypatch.setattr(app_main, "resolve_startup_config", lambda: startup_config)
    monkeypatch.setattr(app_main, "evaluate_startup_readiness", lambda config: startup_readiness)
    monkeypatch.setattr(app_main, "QApplication", FakeApplication)
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)

    result = app_main.main()

    assert result == 0
    assert seen["window_readiness"] is startup_readiness
    assert seen["show_maximized"] is True
    assert seen["preflight_config"] is startup_config


def test_main_skips_async_preflight_in_mock_mode(monkeypatch):
    startup_config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="mock",
        key_source="environment",
        env_path=None,
    )
    startup_readiness = app_main.StartupReadiness(
        provider_name="gemini",
        ready=True,
        user_message="Startup mode: mock fallback ready.",
        block_task_submission=False,
    )
    seen: dict[str, object] = {}

    class FakeApplication:
        def __init__(self, argv):
            seen["argv"] = argv

        def exec(self) -> int:
            return 0

    class FakeWindow:
        def __init__(self, startup_readiness=None) -> None:
            seen["window_readiness"] = startup_readiness

        def showMaximized(self) -> None:
            seen["show_maximized"] = True

        def start_async_preflight(self, config) -> None:
            seen["preflight_config"] = config

    monkeypatch.setattr(app_main, "resolve_startup_config", lambda: startup_config)
    monkeypatch.setattr(app_main, "evaluate_startup_readiness", lambda config: startup_readiness)
    monkeypatch.setattr(app_main, "QApplication", FakeApplication)
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)

    result = app_main.main()

    assert result == 0
    assert seen["window_readiness"] is startup_readiness
    assert seen["show_maximized"] is True
    assert "preflight_config" not in seen


def test_run_preflight_closes_provider_on_success(monkeypatch):
    config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="live-key",
        key_source="environment",
        env_path=None,
    )
    seen: dict[str, bool] = {"probe": False, "close": False, "planner_probe": False}

    class FakeProvider:
        async def probe(self) -> None:
            seen["probe"] = True

        async def close(self) -> None:
            seen["close"] = True

    class FakePlanner:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.client = None

        def probe_live_model(self) -> None:
            seen["planner_probe"] = True

    monkeypatch.setattr(app_main, "make_provider", lambda *args, **kwargs: FakeProvider())
    monkeypatch.setattr(app_main, "_load_cli_planner_class", lambda: FakePlanner)

    readiness = asyncio.run(app_main.run_preflight(config))

    assert readiness.ready is True
    assert seen == {"probe": True, "close": True, "planner_probe": True}


def test_run_preflight_closes_provider_on_failure(monkeypatch):
    config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="live-key",
        key_source="environment",
        env_path=None,
    )
    seen: dict[str, bool] = {"close": False}

    class FakeProvider:
        async def probe(self) -> None:
            raise RuntimeError("API_KEY_INVALID")

        async def close(self) -> None:
            seen["close"] = True

    monkeypatch.setattr(app_main, "make_provider", lambda *args, **kwargs: FakeProvider())

    readiness = asyncio.run(app_main.run_preflight(config))

    assert readiness.ready is False
    assert seen["close"] is True


def test_main_bootstrap_adds_repo_local_dependency_paths(monkeypatch):
    main_path = APP_ROOT / "main.py"
    expected_paths = {
        str(REPO_ROOT.resolve()),
        str((REPO_ROOT / "api-accessibility-poc").resolve()),
        str((REPO_ROOT / "browser-gui-automation").resolve()),
        str((REPO_ROOT / "cli-automation-poc").resolve()),
        str((REPO_ROOT / "audit-debugger" / "src").resolve()),
    }
    filtered = [entry for entry in sys.path if entry not in expected_paths]
    monkeypatch.setattr(sys, "path", [str(APP_ROOT.resolve()), *filtered])

    spec = importlib.util.spec_from_file_location("bootstrap_probe_main", main_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    for expected in expected_paths:
        assert expected in sys.path
