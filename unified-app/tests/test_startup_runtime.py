"""Tests for unified-app startup config and readiness flow."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import main as app_main


def test_resolve_startup_config_reads_gemini_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "shell-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    config = app_main.resolve_startup_config(env_path=env_path)

    assert config.api_key == "shell-key"
    assert config.key_source == "environment"
    assert config.provider_name == "gemini"


def test_resolve_startup_config_falls_back_to_saved_settings_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    class FakeSettingsManager:
        def load(self) -> dict:
            return {"gemini_api_key": "saved-key", "ai_provider": "gemini"}

    monkeypatch.setattr(app_main, "SettingsManager", lambda: FakeSettingsManager())

    config = app_main.resolve_startup_config(env_path=env_path)

    assert config.api_key == "saved-key"
    assert config.key_source == "settings"


def test_resolve_startup_config_reads_openai_key_when_provider_is_openai(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-shell-key")
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    class FakeSettingsManager:
        def load(self) -> dict:
            return {"ai_provider": "openai", "openai_api_key": ""}

    monkeypatch.setattr(app_main, "SettingsManager", lambda: FakeSettingsManager())

    config = app_main.resolve_startup_config(env_path=env_path)

    assert config.provider_name == "openai"
    assert config.api_key == "openai-shell-key"
    assert config.key_source == "environment"


def test_resolve_startup_config_forces_mock_key_when_mock_mode_is_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_MOCK", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    class FakeSettingsManager:
        def load(self) -> dict:
            return {"gemini_api_key": "saved-live-key", "ai_provider": "gemini"}

    monkeypatch.setattr(app_main, "SettingsManager", lambda: FakeSettingsManager())

    config = app_main.resolve_startup_config(env_path=env_path)

    assert config.api_key == "mock"
    assert config.key_source == "environment"


def test_evaluate_startup_readiness_blocks_without_api_key(monkeypatch):
    config = app_main.StartupConfig(
        provider_name="gemini",
        api_key=None,
        key_source="missing",
        env_path=None,
    )

    readiness = app_main.evaluate_startup_readiness(config)

    assert readiness.ready is False
    assert readiness.block_task_submission is True
    assert "missing" in readiness.user_message.lower()


def test_evaluate_startup_readiness_allows_mock_mode_without_blocking():
    config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="mock",
        key_source="environment",
        env_path=None,
    )

    readiness = app_main.evaluate_startup_readiness(config)

    assert readiness.ready is True
    assert readiness.block_task_submission is False
    assert "mock" in readiness.user_message.lower()


@pytest.mark.asyncio
async def test_run_preflight_calls_provider_probe_and_cli_planner(monkeypatch):
    calls: list[str] = []

    class FakeProvider:
        async def probe(self) -> None:
            calls.append("provider")

        async def call(self, messages, *, json_mode=True):
            return ""

        @property
        def provider_name(self):
            return "fake"

    class FakeCLIPlanner:
        def __init__(self, api_key):
            pass

        def probe_live_model(self) -> None:
            calls.append("cli")

    monkeypatch.setattr(app_main, "make_provider", lambda name, key: FakeProvider())
    monkeypatch.setattr(app_main, "_load_cli_planner_class", lambda: FakeCLIPlanner)

    config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="live-key",
        key_source="environment",
        env_path=None,
    )
    readiness = await app_main.run_preflight(config)

    assert readiness.ready is True
    assert readiness.block_task_submission is False
    assert "provider" in calls
    assert "cli" in calls


@pytest.mark.asyncio
async def test_run_preflight_skips_live_probes_in_mock_mode(monkeypatch):
    calls: list[str] = []

    class FakeProvider:
        async def probe(self) -> None:
            calls.append("provider")

    class FakeCLIPlanner:
        def __init__(self, api_key):
            calls.append(f"cli_init:{api_key}")

        def probe_live_model(self) -> None:
            calls.append("cli")

    monkeypatch.setattr(app_main, "make_provider", lambda name, key: FakeProvider())
    monkeypatch.setattr(app_main, "_load_cli_planner_class", lambda: FakeCLIPlanner)

    config = app_main.StartupConfig(
        provider_name="gemini",
        api_key="mock",
        key_source="environment",
        env_path=None,
    )
    readiness = await app_main.run_preflight(config)

    assert readiness.ready is True
    assert readiness.block_task_submission is False
    assert "mock" in readiness.user_message.lower()
    assert calls == []


def test_startup_readiness_dataclass_has_provider_name_field():
    readiness = app_main.StartupReadiness(
        provider_name="openai",
        ready=True,
        user_message="OK",
        block_task_submission=False,
    )
    assert readiness.provider_name == "openai"


def test_apply_startup_readiness_keeps_mock_mode_unblocked():
    observed: dict[str, object] = {}

    class FakeChatPanel:
        def set_startup_state(self, message: str, block_submission: bool = False) -> None:
            observed["message"] = message
            observed["block_submission"] = block_submission

    class FakeOrchestrator:
        def set_startup_guard(self, message):
            observed["guard"] = message

    class FakeEventBus:
        def emit_status(self, message: str, level: str) -> None:
            observed["status_message"] = message
            observed["status_level"] = level

    fake_window = type(
        "FakeWindow",
        (),
        {
            "_force_mock_startup": True,
            "chat_panel": FakeChatPanel(),
            "orchestrator": FakeOrchestrator(),
            "event_bus": FakeEventBus(),
        },
    )()

    readiness = app_main.StartupReadiness(
        provider_name="gemini",
        ready=False,
        user_message="Checking Gemini connection…",
        block_task_submission=True,
    )

    app_main.MainWindow.apply_startup_readiness(fake_window, readiness)

    assert observed["message"] == "Startup mode: mock fallback ready."
    assert observed["block_submission"] is False
    assert observed["guard"] is None
    assert observed["status_level"] == "startup"

