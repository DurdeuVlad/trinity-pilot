"""Regression tests for startup preflight launch from the app entrypoint."""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
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
